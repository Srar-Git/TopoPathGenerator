import argparse
import sys
import wandb
import numpy
import time
import os

from os import path
from graph import Graph
from router import Router
from ga import MetaGA

def parse_args():
    # capture the args with the parser
    parser = argparse.ArgumentParser(description=None)
    parser.add_argument('-i', '--inst', dest='instance', type=str, required=True, help='filepath to problem instance')
    parser.add_argument('-k', '--k-depots', dest='k_depots', type=str, required=True, help='k num tours determined by the depots. ex: -k 0,0')
    parser.add_argument('-d', '--inverse-deployment', dest='inverse_deployment', type=bool, required=False, default=False, help='deploys the vehicles from the last vertex id minus the deployment id specified by -k. Ex n=30 -k 1,2 deploys at vertex ids 28,27')

    # parser.add_argument('-d', '--depots', dest='depots', type=str, required=True, help='the deployment configuration (single, multi). ex: -d single')
    parser.add_argument('-s', '--seeds', dest='seeds', type=str, required=True, help='random seeds to run the ga. ex: -s 1234,3949')
    parser.add_argument('-j', '--heuristics', dest='heuristics', type=str, default='MMMR', required=False, help='the set of heuristics (MMMR, RR). ex: -j MMMR')
    parser.add_argument('--silent', dest='silent', default=False, action='store_true', help='enable silent mode')    
    args = parser.parse_args()

    # check and adjust the parsed args
    args.instance = args.instance.replace(' ', '')
    if not path.exists(args.instance):
        sys.exit("Cannot find instance: " + args.instance)
    args.k_depots = [int(i) for i in args.k_depots.split(',')]
    # args.depots = args.depots.replace(' ', '')
    args.seeds = [int(i) for i in args.seeds.split(',')]
    args.heuristics = args.heuristics.replace(' ', '')
    return args

def main():
    # capturing the arguements
    args = parse_args()

    # Define the print function
    if args.silent or os.getenv('SILENT_MODE') == '1':
        os.environ['SILENT_MODE'] = '1'

    print('Running MetaGA on '+args.instance+', '+str(args.k_depots)+' depots, ' +str(len(args.seeds)) +' seeds, ' + args.heuristics +' heuristics')

    # create the graph
    gph = Graph(args.instance)

    # inverse deployment if specified
    if args.inverse_deployment:
        for i in range(len(args.k_depots)):
            args.k_depots[i] = gph.size_v() - 1 - args.k_depots[i]

    # create a router for constructing tours
    router = Router(gph, args.k_depots, args.heuristics)

    gene_len = 0

    if args.heuristics == 'MMMR':
        gene_len = 2 # for 4 total heuristics
    elif args.heuristics == 'RR':
        gene_len = len(bin(gph.maxVertexDegree)[2:]) # the binary representation

    # find the chromosome lengths based on the heuristics
    chrom_len = gph.size_e() * gene_len

    # define the fitness function
    def evaluate(ga, chromosome, individual_id):
        decoding = []
        for i in range(0, len(chromosome), ga.gene_len):
            decimal = 0
            for j in range(ga.gene_len):
                decimal = decimal * 2 + chromosome[i + j]
            decoding.append(decimal)
            
        router.clear()

        # add first vertex to tour
        for tour in router.tours:
            tour.add_vertex(tour.depot)

        # convert the heuristics to tours
        for h in decoding:
            router.heuristics[h](h)

        # return all tours to their depots
        for tour in router.tours:
            tour.add_vertex(tour.depot)

        # compute objective
        objective = router.get_length_of_longest_tour()
        fitness = 1/objective

        # check if best
        if ga.best_fitness < fitness:
            ga.best_fitness = fitness
            ga.best_binary = numpy.copy(chromosome)
            ga.best_evaluation = ga.num_evaluations
            ga.best_generation = ga.ga_instance.generations_completed
            ga.best_time_seconds = time.time() - ga.run_time_start
            ga.best_solution = router.get_route()
            decoding = numpy.array(decoding)
            heuristic_data = {}
            for h in range(len(router.heuristics)):
                heuristic_data[h] = numpy.count_nonzero(decoding == h)
            ga.best_heuristics = heuristic_data

        return fitness
    
    def log_data(ga):
        wandb.log(ga.log_data)

    # create the metaga
    metaga = MetaGA(gene_len, chrom_len, evaluate, log_data)

    for seed in args.seeds:
        router.set_seed(seed)
        metaga.create(seed)
        wandb.config = {
            'ga' : metaga.config,
            'instance' : gph.config,
            'routing' : router.config
        }

        wandb.init(project="metaga-data", name=gph.name +'_'+ str(seed), config=wandb.config)
        metaga.run()
        wandb.log(metaga.log_data)
        wandb.finish()


    # output the final results
    # print('overall best: ' + str(round(meta_ga.getOverallBestObj(),2)))
    # print('per seed average best: ' + str(round(meta_ga.getAveSeedBestObj(),2)))
    # print('per seed average num evaluations to achieve near best: ' + str(round(meta_ga.getAveNumEvalsToAveBest(),2)))
    # print('per seed reliability: ' + str(round(meta_ga.getReliability(),2)))
    # print('overall time: ' + str(round(meta_ga.seedTimeStats.sum,2)) + 's')

if __name__ == '__main__':
    main()
