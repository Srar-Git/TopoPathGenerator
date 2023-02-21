import argparse
import sys
import numpy
import pandas
import re
import csv

from collections import defaultdict

from scipy.stats import mannwhitneyu
from scipy.stats import ttest_rel
from scipy.stats import ttest_ind

import wandb

from os import path

def parse_args():
    # capture the args with the parser
    parser = argparse.ArgumentParser(description=None)
    parser.add_argument('-f', '--file', dest='data_file', type=str, required=True, help='filepath to data')
    args = parser.parse_args()

    # check and adjust the parsed args
    args.data_file = args.data_file.replace(' ', '')
    if not path.exists(args.data_file):
        sys.exit("Cannot find instance: " + args.data_file)
    return args

def remove_bad_state(df):
    return df.drop(df[(df['State'] == 'killed') | (df['State'] == 'crashed')].index)

def group_data_by_columns(dataframe, *column_keywords):
    ag_data = {} #[num tours][instance][heuristic]

    # Loop through the rows of the dataframe
    for index, row in dataframe.iterrows():
        # Access data for each column by column name
        key = ag_data
        for keyword in column_keywords:
            value = row[keyword]
            if value not in key:
                key[value] = {}
            key = key[value]

        if not ('run best obj' in key):
            key['run best obj']=[]
            key['run best gen']=[]
            key['run best eval']=[]

        key['run best obj'].append(row['run best obj'])
        key['run best gen'].append(row['run best generation'])
        key['run best eval'].append(row['run best evaluation'])

    return ag_data

def exclude_unbalanced_instances(grouped_data):
    # Initialize variables
    to_remove = []
    min_seeds = None
    max_heuristics = 0

    # Loop through the groups and find the minimum number of 'ga.random_seed' values
    for num_tours, tour_data in grouped_data.items():
        for instance, instance_data in tour_data.items():
            max_heuristics = max(max_heuristics, len(instance_data))

    for num_tours, tour_data in grouped_data.items():
        for instance, instance_data in tour_data.items():            
            if len(instance_data) != max_heuristics:
                to_remove.append(((num_tours, instance)))
                continue
            num_seeds = 0
            for heuristic_group, heuristic_data in instance_data.items():
                if len(heuristic_data) == 0:
                    to_remove.append((num_tours, instance))
                elif min_seeds is None or len(heuristic_data) < min_seeds:
                    min_seeds = len(heuristic_data)
                num_seeds += len(heuristic_data)
            if num_seeds % len(instance_data) != 0:
                to_remove.append((num_tours, instance))

    # Remove unbalanced instances from the grouped data
    for group in to_remove:
        print("Excluding routing.num_tours=" + str(group[0]) + ', instance.name='+group[1] + ' due to unbalanced data')
        del grouped_data[group[0]][group[1]]

    return grouped_data    

def produce_statisctics_for_k_values(grouped_data):
    results = {}
    for num_tours in grouped_data:
        data_1 = grouped_data[num_tours]['RR']['run best obj']
        data_2 = grouped_data[num_tours]['MMMR']['run best obj']
        results[num_tours] = {}
        results[num_tours]['mannwhitneyu'] = mannwhitneyu(data_1, data_2)
        results[num_tours]['paired_t-test'] = ttest_rel(data_1, data_2)
        results[num_tours]['two_sample_t-test'] = ttest_ind(data_1, data_2)

    for num_tours in results:
        alpha = 0.05
        for key, value in results[num_tours].items():
            p_val = value[1]
            if p_val < alpha:
                print("For k = " + str(num_tours) + " the " + key + " test indicates a significant difference (p-value = " + str(p_val) + ")")
            else:
                print("For k = " + str(num_tours) + " the " + key + " test indicates no significant difference (p-value = " + str(p_val) + ")")
    print()
    return results


def remove_numeric_suffix(string):
    # Use regular expressions to match the numeric suffix at the end of the string
    match = re.search(r'\d+$', string)
    if match:
        # If a match is found, remove the numeric suffix and return the result
        return string[:match.start()]
    else:
        # If no match is found, return the original string
        return string

def print_num_instances_per_group(data):
    num_instances_per_tour_group = {}
    for num_tours, tour_data in data.items():
        num_instances_per_tour_group[num_tours] = {}
        num_instances_per_tour_group[num_tours]['total'] = 0
        for instance, instance_data in tour_data.items():
            instance_name = remove_numeric_suffix(instance)
            if not (instance_name in num_instances_per_tour_group[num_tours]):
                num_instances_per_tour_group[num_tours][instance_name] = 1
            else:
                num_instances_per_tour_group[num_tours][instance_name] += 1
            num_instances_per_tour_group[num_tours]['total'] += 1
    
    print("Breaking down the number of instances and k-values:")
    # Number of instances per k value
    for num_tours, num_instances in num_instances_per_tour_group.items():
        print(" - k=" + str(num_tours) + " we ran on " + str(num_instances_per_tour_group[num_tours]['total'])+' total unique instances (', end='')
        out = ''
        for instance_name, count in num_instances_per_tour_group[num_tours].items():
            if not instance_name == 'total':
                out += str(count) + ' ' + instance_name + ', '
        print(out[:-2] + ')')

def write_statistics_overall(data, file_path):
    all_data = {}
    for num_tours, tour_data in data.items():
        for instance, instance_data in tour_data.items():
            for heuristic_group, heuristic_data in instance_data.items():
                if not (heuristic_group in all_data):
                    all_data[heuristic_group] = {}
                for seed, seed_data in heuristic_data.items():
                    for data, run_data in seed_data.items():
                        if not (data in all_data[heuristic_group]):
                            all_data[heuristic_group][data] = []
                        all_data[heuristic_group][data].append(run_data[0])

    with open(file_path, 'a') as file:
        file.write('## Overall Summary\n')
        file.write('Comparing heuristic group RR vs MMMR on all k-values, all instances and all runs:\n')
        results = {}
        for data, run_data in all_data['RR'].items():
            results[data] = {}
            results[data]['mannwhitneyu'] = mannwhitneyu(all_data['RR'][data], all_data['MMMR'][data])
            results[data]['paired_t-test'] = ttest_rel(all_data['RR'][data], all_data['MMMR'][data])
            results[data]['two_sample_t-test'] = ttest_ind(all_data['RR'][data], all_data['MMMR'][data])

        alpha = 0.05
        for data, run_data in results.items():
            file.write(" - " + data + ':\n')
            for statistic, statistic_data in run_data.items():
                p_val = statistic_data[1]
                if p_val < alpha:
                    file.write("     - [X] " + statistic + " test indicates a significant difference (p-value: "+ str(alpha) + '<' + str(round(p_val,3)) + ")\n")
                else:
                    file.write("     - [ ] " + statistic + " test indicates no significant difference (p-value: "+ str(alpha) + '<' + str(round(p_val,3)) + ")\n")

def write_per_kvalue_statistics(grouped_data, filename):
    results = defaultdict(dict)
    with open(filename, 'a') as f:
        f.write('## Per k-value\n')
        f.write('Comparing heuristic group RR vs MMMR on individual k-values, all instances and all runs:\n')
        for num_tours, tour_data in grouped_data.items():
            for instance, instance_data in tour_data.items():
                for heuristic_group, heuristic_data in instance_data.items():
                    if not (heuristic_group in results[num_tours]):
                        results[num_tours][heuristic_group] = {}
                    for seed, seed_data in heuristic_data.items():
                        for data, run_data in seed_data.items():
                            if not (data in results[num_tours][heuristic_group]):
                                results[num_tours][heuristic_group][data] = []
                            results[num_tours][heuristic_group][data].append(run_data[0])

            f.write(' - k=' + str(num_tours) + '\n')
            temp_results = {}
            for data, run_data in results[num_tours]['RR'].items():
                temp_results[data] = {}
                temp_results[data]['mannwhitneyu'] = mannwhitneyu(results[num_tours]['RR'][data], results[num_tours]['MMMR'][data])
                temp_results[data]['paired_t-test'] = ttest_rel(results[num_tours]['RR'][data], results[num_tours]['MMMR'][data])
                temp_results[data]['two_sample_t-test'] = ttest_ind(results[num_tours]['RR'][data], results[num_tours]['MMMR'][data])

            alpha = 0.05
            for data, run_data in temp_results.items():
                f.write("     - " + data + ':\n')
                for statistic, statistic_data in run_data.items():
                    p_val = statistic_data[1]
                    if p_val < alpha:
                        f.write("         - [X] " + statistic + " test indicates a significant difference (p-value: "+ str(alpha) + '<' + str(round(p_val,3)) + ")\n")
                    else:
                        f.write("         - [ ] " + statistic + " test indicates no significant difference (p-value: "+ str(alpha) + '<' + str(round(p_val,3)) + ")\n")


def write_per_instance_statistics_to_file(grouped_data, filename):
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Instance', 'Data', 'Heuristic Group', 'mannwhitneyu', 'paired_t-test', 'two_sample_t-test'])
        for num_tours, tour_data in grouped_data.items():
            for instance, instance_data in tour_data.items():
                for heuristic_group, heuristic_data in instance_data.items():
                    results = defaultdict(list)
                    for seed, seed_data in heuristic_data.items():
                        for data, run_data in seed_data.items():
                            results[data].append(run_data[0])
                    for data, run_data in results.items():
                        temp_results = {}
                        temp_results['mannwhitneyu'] = mannwhitneyu(results['RR'], results['MMMR'])
                        temp_results['paired_t-test'] = ttest_rel(results['RR'], results['MMMR'])
                        temp_results['two_sample_t-test'] = ttest_ind(results['RR'], results['MMMR'])
                        alpha = 0.05
                        for statistic, statistic_data in temp_results.items():
                            p_val = statistic_data[1]
                            if p_val < alpha:
                                is_significant = '[X]'
                            else:
                                is_significant = '[ ]'
                            writer.writerow([instance, data, heuristic_group, statistic_data[0], is_significant, p_val])


def main():
    args = parse_args()
    df = pandas.read_csv(args.data_file)

    # Remove state == killed or state == crashed
    cleaned_df = remove_bad_state(df)

    # Group the data and track if known
    grouped_data = group_data_by_columns(cleaned_df, 'routing.num_tours', 'instance.name', 'routing.heuristic_group', 'ga.random_seed')

    # Remove unbalanced runs
    grouped_data = exclude_unbalanced_instances(grouped_data)

    # Output high level infomration
    filename = 'results.md'
    print_num_instances_per_group(grouped_data)
    write_statistics_overall(grouped_data, filename)
    write_per_kvalue_statistics(grouped_data, filename)
    write_per_instance_statistics_to_file(grouped_data, filename)


    # wandb.init(project="metaga-summary", name='best-obj-summary')
    # table = wandb.Table(data=data_best_obj, columns=columns)
    # wandb.log({"avg best objectives": table})

    pass

if __name__ == '__main__':
    main()