# genetic algorithm tsp

#Genetic Algorithm with Dynamic Input Size, Vehicle Priority Queueu and Updated Fake Data Generation

# IMPORTS
import copy
from datetime import datetime
from iteration_utilities import random_permutation
import math
import random
from typing import List, Optional, Tuple, Dict
from collections import defaultdict

# Libraries for Parallel Processing
import multiprocessing
from joblib import Parallel, delayed
from tqdm import tqdm

# Project Files to be Imported
from src.utilities.vrp_helper import get_based_and_load_data
from src.vrp.vehicles_pq import VehiclesPQ
#from src.supabase_help.get_duration_matrix_mapbox import get_data

# PARAMETERS AND DATA GENERATION
N = 10 # number of shops to be considered
K = 0
Q = 11
M = 1
DIST_DATA = None
vehicles_start_times = None
IGNORE_LONG_TRIP = True # used in the duration calculation method
RANDOM_PERM_COUNT = 5000 # Genetic Algorithm initial sample size
DIST_DATA, LOAD = get_based_and_load_data(input_file_load = None, n=N+1, per_km_time=0.25) # generate the distance data matrix
#DIST_DATA = get_data()#DIST_DATA = get_data()
MIN_ENTRY_COUNT = 25 # used for deciding on making or skipping the selection & replacement step
ITERATION_COUNT = 30 # limits the number of iterations for the genetic algorithm
INF = float("inf")
N_TIME_SLICES = 12
#DEPOT_TUPLE = (0, -1, "Depot")

N_TIME_ZONES = 12  # hours = time slices
TIME_UNITS = 3600  # hour = 60 minutes
DEPOT = 0

#NODES = get_nodes()
#NODES = NODES[:N]

#######################################################################################################################
#######################################################################################################################
# GENETIC ALGORITHM LOGIC


def random_selection(permutations, sel_count, already_selected = []):
    """
        Randomly selects 'sel_count' many permutations and starts the process with the permutations available in
        'already selected' list

        :param permutations: all available permutations
        :param sel_count: number of permutations to be selected
        :param already_selected: previously selected permutations
    """
    # select 'sel_count' many permutations in a random fashion
    selection_indices = []
    while len(already_selected) < sel_count:
        rand_index = random.randint(0, len(permutations) - 1)
        while rand_index in selection_indices:
            rand_index = random.randint(0, len(permutations) - 1)

        already_selected.append(permutations[rand_index])
        selection_indices.append(rand_index)

    return already_selected

def reverse_insert_probability_list(permutations, probability_list, inf_start_at_index):
    """
            Reverses the probability ranges to be matched with each permutation available
            This allows the permutations with smaller duration to get a bigger portion
            in the fitness proportional selection

            :param permutations: all available permutations
            :param probability_list: duration based fitness intervals
            :param inf_start_at_index: indicates the index at which the infeasible permutations start getting listed in
                                        the 'permutations' list
    """

    # the fitness and total cost are inversely related
    # permutations with shorter duration will get higher fitness value

    # divide the probability list into two depending on the inf total duration values
    probability_list_non_inf_values = probability_list[:inf_start_at_index]
    probability_list_inf_values = probability_list[inf_start_at_index:]

    # reverse the duration based probability list and assign bigger portions for the permutations with lower duration
    probability_list_non_inf_values.reverse()
    current_fitness_level = 0
    for index in range(0, len(probability_list_non_inf_values)):

        if not len(permutations[index])>=7:

            permutations[index].append([current_fitness_level, current_fitness_level + probability_list_non_inf_values[index]])
            current_fitness_level = current_fitness_level + probability_list_non_inf_values[index]

        else:
            permutations[index][6] = ([current_fitness_level, current_fitness_level + probability_list_non_inf_values[index]])
            current_fitness_level = current_fitness_level + probability_list_non_inf_values[index]

    # fills in the rest of the probability range values for the remaining permutations in the list
    count = 0
    for index in range(len(probability_list_non_inf_values), len(permutations)):

        if not len(permutations[index])>=7:
            permutations[index].append([current_fitness_level, current_fitness_level + probability_list_inf_values[count]])
            current_fitness_level = current_fitness_level + probability_list_inf_values[count]

        else:
            permutations[index][6] = ([current_fitness_level, current_fitness_level + probability_list_inf_values[count]])
            current_fitness_level = current_fitness_level + probability_list_inf_values[count]

        count = count + 1

    return permutations

def calculate_fitness_level(remaining_permutations):
    """
             Based on the previously calculated duration information, calculate the fitness level of each permutation

            :param remaining_permutations: all available permutations
    """
    #print("SELECTION: Calculating fitness level...")

    sorted(remaining_permutations, key=lambda x: x[2], reverse=False)
    shortest_duration = remaining_permutations[0][2]
    total_sum = 0

    for elem in remaining_permutations:
        # if the permutation is not infeasible then add the total duration to the total sum
        if elem[2] != math.inf:
            total_sum = total_sum + elem[2]
        # if the permutation is infeasible then add the shortest duration of the permutation list as the
        # total duration of the infeasible solution so that the fitness value distribution would be balanced
        else:
            total_sum = total_sum + shortest_duration

    probability_list = []
    inf_starts_at_index = 0

    # the index at which the infeasible solutions start is found and stored for it to be used in the reversion method
    for index in range(0, len(remaining_permutations)):

        # find the non-reversed fitness level of each permutation
        if remaining_permutations[index][2] != math.inf:
            fitness_level = remaining_permutations[index][2] / total_sum
        else:
            fitness_level = (shortest_duration) / total_sum

            if inf_starts_at_index == 0: # if it has been already changed then do not change it again
                inf_starts_at_index = index

        # store the non-reversed fitness level
        probability_list.append(fitness_level)

    #find the original/adjusted/reversed fitness levels
    remaining_permutations = reverse_insert_probability_list(remaining_permutations, probability_list, inf_starts_at_index)

    return remaining_permutations


def select_based_on_fitness_proportional(permutations):
    """
                 Select a predefined number of permutations from the given permutations list

                :param permutations: all available permutations
    """

    start = datetime.now()
    mode = "FITNESS"
    selection_len = int(len(permutations)*5 / 8)
    selected = []

    # continue fitness proportional selection until the selection length is reached
    while len(selected) < selection_len:

        end = datetime.now()

        if (end - start).seconds >= 0.6:
            # current implementation of the fitness proportional method might take some time
            # current time limit is 10 seconds
            # if the threshold is exceeded than selection mode is switched to RANDOM selection
            mode = "RANDOM"
            break

        else: # time limit has not reached, continue fitness proportional selection
            # generate random number between 0 and 1
            rand = random.uniform(0, 1)

            # find the permutation which has this value in its own fitness range
            for index in range(0, len(permutations)):
                elem = permutations[index]
                if elem[6][0] <= rand <= elem[6][1] and elem[1]:
                    selected.append(elem)
                    break

    if mode == "RANDOM":
        return random_selection(permutations = permutations, sel_count=selection_len, already_selected=selected)

    return selected



# REPLACEMENT

def deterministic_best_n_replacement(permutations, n=-1):
    """
              Sort the permutations based on duration and return the best n
              If n is not specified simply get the first half of the list

              :param permutations: all available permutations
              :param n: number of items to be selected
    """

    if n != -1:
        replacement_count = n
    else:
        replacement_count = int(len(permutations) / 2)

    return sorted(permutations, key=lambda x: x[2], reverse=False)[:replacement_count]


# REPRODUCTION

def swap_mutation(permutations, VST, dist_data, M, Q, load, demand_dict, sn, cancelled_customers, do_load_unload):
    """
                  Select two random indices and swap these indices
                  If the mutated permutation has a longer duration than the previous permutation, simply revert the swap
                  If the mutated permutation has a smaller duration than the previous permutation, keep the mutation

                  :param permutations: all available permutations
    """


    DIST_DATA = dist_data
    vehicles_start_times = VST

    for index in range(0, len(permutations)):

        single_perm = permutations[index]
        #single_perm = [single_perm]
        count = 0
        while count < 10:  # threshold for the number of inversion mutation to be applied, for now it is 10
            # select two random positions
            # indices 0 and -1 are not included
            pos1 = random.randint(1, len(single_perm[0])-1) # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end
            pos2 = random.randint(1, len(single_perm[0])-1) # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end

            # if two positions are not equal and none of the positions equal to DEPOT
            if pos1 != pos2 and single_perm[0][pos1] != DEPOT and single_perm[0][pos2] != DEPOT:

                # swap the indices
                temp = single_perm[0][pos1]
                single_perm[0][pos1] = single_perm[0][pos2]
                single_perm[0][pos2] = temp
                # calculate the new duration
                a,b, route_sum_time, vehicle_routes, vehicle_times  = calculate_duration(permutation = single_perm[0], VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q, load=load, demand_dict=demand_dict, sn=sn, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
                #a, b = calculate_duration(single_perm[0])

                # if the new duration is shorter than the previous one keep it
                if a < single_perm[2]:
                    single_perm[2], single_perm[1] = a, b
                    single_perm[3], single_perm[4], single_perm[5] = route_sum_time, vehicle_routes, vehicle_times
                    #single_perm.append(route_sum_time)
                    #single_perm.append(vehicle_routes)
                    #single_perm.append(vehicle_times)

                # if the new duration is longer than the previous one revert the changes
                else:
                    temp = single_perm[0][pos1]
                    single_perm[0][pos1] = single_perm[0][pos2]
                    single_perm[0][pos2] = temp
            count = count + 1
    return permutations

def scramble_mutation(permutations, VST, dist_data, M, Q, load, demand_dict, sn, cancelled_customers, do_load_unload):
    """
                      Select two random indices
                      Shuffle everything that stays between these two randomly selected indices

                      :param permutations: all available permutations
    """

    DIST_DATA = dist_data
    vehicles_start_times = VST

    for index in range(0, len(permutations)):
        # get the current permutation
        single_perm = permutations[index]
        #single_perm = [single_perm]

        count = 0
        while count < 1: # threshold for the number of inversion mutation to be applied, for now it is 1
            # select two random positions
            # indices 0 and -1 are not included
            #pos1 = random.randint(1, len(single_perm[0]) - 2)
            #pos2 = random.randint(1, len(single_perm[0]) - 2)

            pos1 = random.randint(1, len(single_perm[0])-1)  # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end
            pos2 = random.randint(1, len(single_perm[0])-1)  # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end

            # save the lower and upper bounds as a pair
            bound = (pos1, pos2) if pos1 < pos2 else (pos2, pos1)

            if pos1 != pos2:
                # get the part before the selected portion
                lower_part = single_perm[0][0:bound[0]]
                # get the part after the selected portion
                upper_part = single_perm[0][bound[1] + 1:]
                # get the portion to be reversed
                subpart = single_perm[0][bound[0]:bound[1] + 1]
                # scramble the related portion
                random.shuffle(subpart)

                # construct the permutation with the reversed portion
                single_perm[0] = lower_part + subpart + upper_part

                # calculate new duration and save
                a, b, route_sum_time, vehicle_routes, vehicle_times= calculate_duration(single_perm[0], VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q,load=load, demand_dict=demand_dict, sn=sn, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
                #a, b = calculate_duration(single_perm[0])
                single_perm[2], single_perm[1] = a, b
                single_perm[3], single_perm[4], single_perm[5] = route_sum_time, vehicle_routes, vehicle_times
                #single_perm.append(route_sum_time)
                #single_perm.append(vehicle_routes)
                #single_perm.append(vehicle_times)

            count = count + 1
    return permutations

def inversion_mutation(permutations,  VST, dist_data, M, Q,load, demand_dict, sn,  cancelled_customers, do_load_unload):
    """
                          Select two random indices
                          Reverse everything that stays between these two randomly selected indices

                          :param permutations: all available permutations
    """

    DIST_DATA = dist_data
    vehicles_start_times = VST

    for index in range(0, len(permutations)):
        # get the current permutation
        single_perm = permutations[index]
        #single_perm = [single_perm]
        count = 0
        while count < 1: # threshold for the number of inversion mutation to be applied, for now it is 1
            # select two random positions
            # indices 0 and -1 are not included
            #pos1 = random.randint(1, len(single_perm[0]) - 2)
            #pos2 = random.randint(1, len(single_perm[0]) - 2)

            pos1 = random.randint(1, len(single_perm[0])-1)  # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end
            pos2 = random.randint(1, len(single_perm[0])-1)  # vrp version has -2 bcz of DEPOT nodes at the beginning and at the end

            # save the lower and upper bounds as a pair
            bound = (pos1, pos2) if pos1 < pos2 else (pos2, pos1)

            if pos1 != pos2:

                # get the part before the selected portion
                lower_part = single_perm[0][0:bound[0]]
                # get the part after the selected portion
                upper_part = single_perm[0][bound[1]+1:]
                # get the portion to be reversed
                subpart = single_perm[0][bound[0]:bound[1]+1]
                # reverse the related portion
                list.reverse(subpart)
                # construct the permutation with the reversed portion
                single_perm[0] = lower_part + subpart + upper_part

                # calculate new duration and save
                a, b, route_sum_time, vehicle_routes, vehicle_times = calculate_duration(single_perm[0], VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q,load=load, demand_dict=demand_dict, sn=sn, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
                #a, b = calculate_duration(single_perm[0])
                single_perm[2], single_perm[1] = a, b
                single_perm[3], single_perm[4], single_perm[5] = route_sum_time, vehicle_routes, vehicle_times
                #single_perm.append(route_sum_time)
                #single_perm.append(vehicle_routes)
                #single_perm.append(vehicle_times)
            count = count + 1

    return permutations

def genetic_algorithm(population, N_in, M_in, k_in, q_in, W_in, duration_in, demand_in, ist_in, demand_dict, sn, cancelled_customers, do_load_unload):
    """
                          Apply Mutation and Selection & Replacement operations
                          based on the random probabilities generated

                          :param population: all available permutations
    """

    N = N_in  # number of shops to be considered
    K = k_in
    Q = q_in
    M = M_in
    DEPOT = W_in
    DIST_DATA = duration_in
    LOAD = demand_in
    vehicles_start_times = ist_in

    new_population = None # empty variable for the output population

    # assigned probabilities for each mutation option
    SWAP_MUTATION_PROB = (0, 0.33)
    INVERSION_MUTATION_PROB = (0.33, 0.66)
    SCRAMBLE_MUTATION_PROB = (0.66, 1)

    # assigned probabilities for each selection & replacement option
    SELECTION_PROB = (0, 0)
    REPLACEMENT_PROB = (0, 0.5)
    RANDOM_SELECTION_PROB = (0.5, 0.75)
    NO_SELECTION_REPLACEMENT_PROB = (0.75, 1)

    # generate random probabilities
    rand_phase_1 = random.uniform(0,1)
    rand_phase_2 = random.uniform(0,1)

    # PHASE 1 MUTATION
    updated_population = population
    if SWAP_MUTATION_PROB[0] <= rand_phase_1 <= SWAP_MUTATION_PROB[1]:
        #print("REPRODUCTION: applying swap mutation...")
        updated_population = swap_mutation(population, VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q,load=LOAD, demand_dict=demand_dict, sn=sn,  cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
    elif INVERSION_MUTATION_PROB[0] <= rand_phase_1 <= INVERSION_MUTATION_PROB[1]:
        #print("REPRODUCTION: applying inversion mutation...")
        updated_population = inversion_mutation(population, VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q,load=LOAD, demand_dict=demand_dict, sn=sn, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
    elif SCRAMBLE_MUTATION_PROB[0] <= rand_phase_1 <= SCRAMBLE_MUTATION_PROB[1]:
        #print("REPRODUCTION: applying scramble mutation...")
        updated_population = scramble_mutation(population, VST = vehicles_start_times, dist_data = DIST_DATA, M=M, Q=Q,load=LOAD, demand_dict=demand_dict, sn=sn, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)

    # PHASE 2 SELECTION & REPLACEMENT
    if len(updated_population) > MIN_ENTRY_COUNT:
        # if the number of permutations available is less than MIN_ENTRY_COUNT do not apply selection & replacement
        if SELECTION_PROB[0] <= rand_phase_2 <= SELECTION_PROB[1]:
            #print("SELECTION & REPLACEMENT: applying selection...")
            # first calculate the fitness value of all permutations
            population_with_fitness = calculate_fitness_level(updated_population)
            # then select permutations based on fitness value
            new_population = select_based_on_fitness_proportional(population_with_fitness)

            pass
            # post process the permutations
            #for elem in new_population:
            #    if len(elem) > 4:
            #        del elem[4]

        elif REPLACEMENT_PROB[0] <= rand_phase_2 <= REPLACEMENT_PROB[1]:
            #print("SELECTION & REPLACEMENT: applying replacement...")
            new_population = deterministic_best_n_replacement(updated_population)

        elif RANDOM_SELECTION_PROB[0] <= rand_phase_2 <= RANDOM_SELECTION_PROB[1]:
            #print("SELECTION & REPLACEMENT: applying random selection...")
            new_population = random_selection(updated_population, (len(updated_population)*5/8), already_selected=[])

        elif NO_SELECTION_REPLACEMENT_PROB[0] <= rand_phase_2 <= NO_SELECTION_REPLACEMENT_PROB[1]:
            #print("SELECTION & REPLACEMENT: no operation...")
            new_population = updated_population
    else:
        new_population = updated_population

    return new_population

#######################################################################################################################
#######################################################################################################################
# HELPER FUNCTIONS
def get_tours(permutations):
    """
                              Find the tours of all permutations
                              Save this information in the given object

                              :param permutations: all available permutations
    """

    # returns the tour nodes and available capacity per tour
    state = "BEGINNING"

    all_tours = []

    for elem in permutations:
        current_tour = []
        for shop_index in range(0, len(elem[0])):

            if elem[0][shop_index] == DEPOT and state == "BEGINNING":
                state = "NEW_TOUR_STARTED"
                current_tour.append(elem[0][shop_index])

            elif elem[0][shop_index] == DEPOT and state == "NEW_TOUR_STARTED" and shop_index == len(elem[0]) - 1:
                # last element of the permutation is reached
                # the tour is stopped and saved
                state = "BEGINNING"
                current_tour.append(elem[0][shop_index])

                all_tours.append(current_tour)
                current_tour = []

            elif elem[0][shop_index] == DEPOT and state == "NEW_TOUR_STARTED" and shop_index != len(elem[0]) - 1:
                # last element of the permutation is NOT reached
                # the tour is stopped and saved
                # new tour has started
                state = "NEW_TOUR_STARTED"
                current_tour.append(elem[0][shop_index])

                all_tours.append(current_tour)
                current_tour = []
                current_tour.append(DEPOT)

            elif elem[0][shop_index] != DEPOT and state == "NEW_TOUR_STARTED":
                # last element of the permutation is NOT reached
                # the tour is NOT stopped
                # current shop is added and tour continues
                current_tour.append(elem[0][shop_index])
            else:
                pass

        elem.append(all_tours)
        all_tours = []

    return permutations


#######################################################################################################################
#######################################################################################################################
# DURATION CALCULATION AND RUN

LOADING_TIME_INIT = 30
LOADING_TIME_PER_UNIT = 10
UNLOADING_DEPOT_TIME_INIT = 30
UNLOADING_DEPOT_TIME_PER_UNIT = 10
UNLOADING_CUSTOMER_TIME_INIT = 60
UNLOADING_CUSTOMER_TIME_PER_UNIT = 10




def helper(
    q: int,
    m: int,
    ignore_long_trip: bool,
    cycles: List[List[int]],
    duration: List[List[List[float]]],
    load: List[int],
    vehicles_start_times: List[float],
    demand_dict: Dict[int, int]
) -> Tuple[float, float, Optional[defaultdict], Optional[defaultdict]]:
    """
    Calculates total time it takes to visit the locations for the latest driver, sum of the durations of each driver and
        the routes for each driver, given list of cycles

    :param q: Capacity of vehicle
    :param m: Max number of vehicles
    :param ignore_long_trip: Flag to ignore long trips
    :param cycles: The cycles to be assigned where one cycle is demonstrated as [DEPOT, c_i, ..., c_j, DEPOT]
    :param duration: Dynamic duration data of NxNx12
    :param load: Loads of locations
    :param vehicles_start_times: List of (expected) start times of the vehicle. If not specified, they are all assumed
        as zero.
    :return: Total time it takes to visit the locations for the latest driver, sum of the durations of each driver, the
        routes for each driver and the travel duration for each driver
    """

    ############################
    #new cd

    # Initialize vehicle id to cycles and times mapping
    vehicle_routes = defaultdict(list)

    # Initialize the PQ of vehicles (drivers) with given (expected) start time
    vehicles_pq = VehiclesPQ(vehicles_start_times)

    # Cycle: [DEPOT, customer_1, customer_2, ..., customer_k, DEPOT]
    # Cycles: [cycle_1, cycle_2, ...]
    for cycle in cycles:
        # Get the vehicle (driver) with the earliest available time
        vehicle_t, vehicle_id = vehicles_pq.get_vehicle()
        last_node = DEPOT
        curr_capacity = q
        total_load = 0
        for customer in cycle:
            total_load += demand_dict[customer]
        if total_load > 0:
            vehicle_t += LOADING_TIME_INIT + LOADING_TIME_PER_UNIT * total_load
        # Go over each edge in the cycle
        for node in cycle[1:]:
            # Update capacity and check if it exceeds the initial capacity
            curr_capacity -= demand_dict[node]
            if curr_capacity < 0:
                return INF, INF, None, None
            # Determine the hour and check if it exceeds the number of time zones (based on ignore_long_trip)
            hour = int(vehicle_t / TIME_UNITS)
            if not ignore_long_trip:
                hour = min(hour, N_TIME_ZONES - 1)
            if hour >= N_TIME_ZONES:
                return INF, INF, None, None
            # Update time and node
            vehicle_t += duration[last_node][node][hour]
            if node != DEPOT:
                vehicle_t += UNLOADING_CUSTOMER_TIME_INIT + UNLOADING_CUSTOMER_TIME_PER_UNIT *  demand_dict[node]
            last_node = node
        # Update PQ with the chosen vehicle and updated time
        vehicles_pq.put_vehicle(vehicle_t, vehicle_id)
        vehicle_routes[vehicle_id].append(cycle)

    # Pull elements from PQ and update vehicle id to cycles and times mapping
    # route_max_time: max of duration among all vehicles (drivers)
    # route_sum_time: sum of duration of all vehicles (drivers)
    route_max_time, route_sum_time, vehicle_times = vehicles_pq.get_route_and_vehicle_times()

    # Check if it exceeds the number of time zones (based on ignore_long_trip)
    if ignore_long_trip and route_max_time >= N_TIME_ZONES * TIME_UNITS:
        return INF, INF, None, None

    # Return :)
    return route_max_time, route_sum_time, vehicle_routes, vehicle_times


def calculate_duration_perm(
    perm: List[int],
    duration: List[List[List[float]]],
    vehicles_start_times: Optional[List[float]],
    q: int,
    m: int,
    load: List[int],
    demand_dict: Dict[int, int],
    ignore_long_trip: bool = False


) -> Tuple[float, float, Optional[defaultdict], Optional[defaultdict]]:
    """
    Calculates total time it takes to visit the locations for the latest driver, sum of the durations of each driver and
        the routes for each driver, given permutation of nodes

    :param q: Capacity of vehicle
    :param m: Max number of vehicles
    :param ignore_long_trip: Flag to ignore long trips
    :param perm: The locations to visit in order
    :param duration: Dynamic duration data of NxNx12
    :param load: Loads of locations
    :param vehicles_start_times: List of (expected) start times of the vehicle. If not specified, they are all assumed
        as zero.
    :return: Total time it takes to visit the locations for the latest driver, sum of the durations of each driver, the
        routes for each driver and the travel duration for each driver
    """
    perm = list(perm)
    perm.append(DEPOT)

    cycles = []
    last_cycle = []
    for node in perm:
        if node == DEPOT:
            if len(last_cycle) > 0:
                cycle = [DEPOT]
                cycle.extend(last_cycle)
                cycle.append(DEPOT)
                cycles.append(cycle)
                last_cycle = []
        else:
            last_cycle.append(node)

    return helper(q, m, ignore_long_trip, cycles, duration, load, vehicles_start_times, demand_dict=demand_dict)

def calculate_duration_load_unload_tsp(
    current_time: float, #vehicle start time
    current_location: int, #start node
    perm: List[int],
    duration: List[List[List[float]]],
    load: List[int],
    ignore_long_trip: bool,
    do_loading_unloading: bool, # boolean OK, true cagir, baslicagin start nodeun laoding unloading var mi onu soyluor
    cancelled_customers: List[int], # cc
    demand_dict: Dict[int, int]
) -> Tuple[float, float, Optional[defaultdict], Optional[defaultdict]]: #Tuple[float, Optional[List[int]]]:
    """
    Calculates total time it takes to visit the locations and the route for the given order of customers

    :param current_time: Current time
    :param current_location: Current (starting) location
    :param perm: Customers to be visited in order
    :param duration: Dynamic duration data of NxNx12
    :param load: Loads of locations
    :param ignore_long_trip: Flag to ignore long trips
    :param do_loading_unloading: Spend time to do loading/unloading at the current_location
    :param cancelled_customers: Customers where regarding orders are cancelled
    :return: Total time it takes to visit the locations in the given order and the corresponding route
    """
    current_time_start = copy.deepcopy(current_time)
    route = [current_location] + perm + [DEPOT]
    last_node = current_location

    if do_loading_unloading:
        if current_location != DEPOT:
            current_time += UNLOADING_CUSTOMER_TIME_INIT + UNLOADING_CUSTOMER_TIME_PER_UNIT * demand_dict[current_location]
        else:
            total_load = 0
            for customer in route:
                total_load += demand_dict[customer]
            if total_load > 0:
                current_time += LOADING_TIME_INIT + LOADING_TIME_PER_UNIT * total_load

    for node in route[1:]:
        hour = int(current_time / TIME_UNITS)
        if not ignore_long_trip:
            hour = min(hour, N_TIME_ZONES - 1)
        if hour >= N_TIME_ZONES:
            return INF, None
        current_time += duration[last_node][node][hour]
        if node != DEPOT:
            current_time += UNLOADING_CUSTOMER_TIME_INIT + UNLOADING_CUSTOMER_TIME_PER_UNIT * demand_dict[node]
        else:
            total_load = 0
            for customer in cancelled_customers:
                total_load += demand_dict[customer]
            if total_load > 0:
                current_time += UNLOADING_DEPOT_TIME_INIT + UNLOADING_DEPOT_TIME_PER_UNIT * total_load
        last_node = node

    if ignore_long_trip and current_time >= N_TIME_ZONES * TIME_UNITS:
        return INF, None

    tour_len = current_time-current_time_start
    tour_len_dict = {}
    tour_len_dict[0] = tour_len

    tour_dict = {}
    tour_dict[0] = route
    return current_time, perm, tour_dict, tour_len

def calculate_duration(permutation, VST, dist_data, M, Q, load, demand_dict,sn, cancelled_customers, do_load_unload):
    #Q = Q + len(permutation)
    #if sn !=None and sn!=0:
    #    permutation.insert(1, sn)
    #    sn_index = permutation.index(sn)
    #    del permutation[sn_index]
    #    permutation.insert(1, sn)

    #route = [0]
    route=[]
    for elem in permutation:
        node = elem
        route.append(node)

    if VST is None:
        VST = [0 for _ in range(M)]
    else:
        assert len(VST) == M, f"Size of the vehicles_start_times should be {M}"

    if not type(VST) == float:
        vehicles_start_times = VST[0]

    route_max_time, route, vehicle_routes, vehicle_times = calculate_duration_load_unload_tsp(current_time=vehicles_start_times, current_location=sn, perm=permutation, duration=dist_data, load = load, ignore_long_trip=False, do_loading_unloading=do_load_unload, cancelled_customers=cancelled_customers, demand_dict=demand_dict)
    #route_max_time, route_sum_time, vehicle_routes, vehicle_times = calculate_duration_perm(q=Q, m= M, perm=route, duration=dist_data, vehicles_start_times=VST, load = load, demand_dict = demand_dict)
    #if sn!=None:
    #    del route[route.index(sn)]
    #    del vehicle_routes[0][0][1]
        #del vehicle_routes[0]
    return route_max_time, permutation, route_max_time, vehicle_routes, vehicle_times


def clean_permutations(permutations):
    """
            Removes all values from the previous iteration of the genetic algorithm

            :param permutations: all available permutations
    """

    # simply removes the additional data appended in the earlier iterations of the genetic algorithm
    #for perm in permutations:
    #    if len(perm) == 9:
    #        del perm[8]

    return permutations

def check_neighbor(perm):

    # randomly generated permutations can not have two DEPOT nodes side by side. In that case shift places.

    for i in range(1, len(perm)):
        if perm[i] == perm[i-1] == DEPOT:
            #perm = correct_neighbor_order(perm = perm, index = i)
            return False

    if perm[0] == DEPOT or perm[-1] == DEPOT:
        return False

    return True

def calculate_demand_dict(customer_list, demand_list):

    demand_dict = {}

    demand_dict[0] = 0

    #print(customer_list)
    #print(demand_list)

    for i in range(0,len(customer_list)):

        demand_dict[customer_list[i]] =  demand_list[i+1]


    #demand_dict[start_node] =
    return demand_dict

def ga(N_in, M_in, k_in, q_in, W_in, duration_in, ist_in, start_node, customer_list, demand_dict,cancelled_customers=[], do_load_unload=True,permutations = None):
    """
                Main method that controls the mode of the genetic algorithm
                If no input is given than it starts with population generation and runs genetic algorithm
                If 'permutations' list is given then skips population generation and runs genetic algorithm

                :param permutations: all available permutations
    """

    N = N_in  # number of shops to be considered
    K = k_in
    Q = q_in
    M = M_in
    DEPOT = W_in
    DIST_DATA = duration_in
    #LOAD = demand_in
    vehicles_start_times = ist_in
    #demand_dict = calculate_demand_dict(customer_list=customer_list, demand_list=LOAD)
    # main method of the program
    # all threads run this method in parallel

    # if the given input to this method is none, then a new population is generated from scratch
    if permutations is None:
        NODES = []
        if len(customer_list) != 0:
            NODES = copy.deepcopy(customer_list)
        else:
            NODES.extend(range(1, N + 1))


        NODES_LIST = []
        # there can be different number of tours in each permutation
        # the upper limit is K
        # any permutation between 1 tour and up to K tours are generated
        # the mutation operations work against infeasible solutions
        #if start_node != None:
        #    sn_index = NODES.index(start_node)
        #    del NODES[sn_index]




        #for k in range(0,K):
        #    current_NODES = copy.deepcopy(NODES)



        NODES_LIST.append(NODES)

        #NODES_LIST.append(NODES)
        random_generated_perm = []

        #print("Generating random population with size: ", RANDOM_PERM_COUNT)

        while len(random_generated_perm) <= RANDOM_PERM_COUNT:

            for elem in NODES_LIST:



                # random permutation is generated
                random_perm = random_permutation(elem)
                # converted to list
                random_perm = list(random_perm)

                # if sn is not node add it to the beginning of the current chain
                #if start_node != None:
                #    random_perm.insert(0, start_node)

                # DEPOT is added to the beginning and to the end
                #if start_node == DEPOT:
                #random_perm.insert(0, start_node)
                #random_perm.append(DEPOT)

                # duration and shop indices are calculated
                total_dist, route, route_sum_time, vehicle_routes, vehicle_times = calculate_duration(permutation=random_perm, dist_data=DIST_DATA, VST= vehicles_start_times, M=M ,Q=Q, load=LOAD, demand_dict=demand_dict, sn=start_node, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
                #total_dist, route = calculate_duration(permutation=random_perm, dist_data=DIST_DATA)
                # constructed a tuple of three elements 1) permutation 2) shop indices 3) total duration
                random_perm_tuple = [route, route, total_dist, route_sum_time, vehicle_routes, vehicle_times]
                #random_perm_tuple = [random_perm, route, total_dist, route_sum_time, vehicle_routes, vehicle_times]
                random_generated_perm.append(random_perm_tuple)

        # generated permutation list is sorted based on total duration (i.e. x[2])
        random_generated_perm = sorted(random_generated_perm, key=lambda x: x[2], reverse=False)
        # generated tours of each permutation is calculated and saved
        get_tours(random_generated_perm)
        # genetic algorithm code is called
        res = genetic_algorithm(population = random_generated_perm, N_in = N, M_in = M, k_in = K, q_in = Q, W_in = DEPOT, duration_in = DIST_DATA, demand_in = LOAD, ist_in = vehicles_start_times, demand_dict=demand_dict, sn = start_node, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
        # temporary variables used in the last iteration of the genetic algorithm
        res = clean_permutations(res)
        # results are sorted based on total duration (i.e. x[2])
        res = sorted(res, key=lambda x: x[2], reverse=False)

    else:
        # permutations exist, do not generate new data and continue with the given input
        res = genetic_algorithm(population = permutations, N_in = N, M_in = M, k_in = K, q_in = Q, W_in = DEPOT, duration_in = DIST_DATA, demand_in = LOAD, ist_in = vehicles_start_times, demand_dict=demand_dict, sn=start_node, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload)
        # temporary variables used in the last iteration of the genetic algorithm
        res = clean_permutations(res)
        # results are sorted based on total duration (i.e. x[2])
        res = sorted(res, key=lambda x: x[2], reverse=False)

    return res

def run(N_in, M_in, k_in, q_in, W_in, duration_in, ist_in, multithreaded,demand_dict, start_node = None, customer_list = [],  cancelled_customers = [], do_load_unload = True):
    N = N_in  # number of shops to be considered
    K = k_in
    Q = q_in
    M = M_in
    DEPOT = W_in
    DIST_DATA = duration_in
    #LOAD = demand_in
    vehicles_start_times = ist_in
    #demand_dict = calculate_demand_dict(customer_list=customer_list, demand_list=LOAD)


    start_time = datetime.now()  # used for runtime calculation
    entries = []

    if multithreaded:
        # get the number of available cores
        num_cores = int(multiprocessing.cpu_count())
    else:
        num_cores = 1

    # run num_cores many threads in parallel
    # at the beginning there exists no input for the run method, thus tqdm library does not prepare any inputs
    inputs = tqdm(num_cores * [1], disable=True)
    processed_list = Parallel(n_jobs=num_cores)(delayed(ga)(N_in = N, M_in = M, k_in = K, q_in = Q, W_in = DEPOT, duration_in = DIST_DATA, ist_in = vehicles_start_times, start_node = start_node, customer_list = customer_list, permutations=None, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload, demand_dict=demand_dict) for i in inputs)

    # save the output of the current iteration
    #entries.append(copy.deepcopy(processed_list))

    iteration_count = 0

    best = []

    while iteration_count < ITERATION_COUNT:
        # tqdm library prepares the previously generated permutations for the next iteration
        inputs = tqdm(processed_list, disable=True)
        processed_list = Parallel(n_jobs=num_cores)(delayed(ga)(N_in = N, M_in = M, k_in = K, q_in = Q, W_in = DEPOT, duration_in = DIST_DATA, ist_in = vehicles_start_times, start_node = start_node, customer_list = customer_list, permutations=i, cancelled_customers=cancelled_customers, do_load_unload=do_load_unload, demand_dict=demand_dict) for i in inputs)

        #
        current_best_entries = []
        thread_index = 1
        for elem in processed_list:

            # calculate total element count and total sum
            #total_elem_count = sum(1 if i[2] != math.inf else 0 for i in elem)
            #total_sum = sum(i[2] if i[2] != math.inf else 0 for i in elem)

            #if total_elem_count == 0:
                # prevents division by zero error in some cases
                #total_elem_count = 1
            elem = sorted(elem, key=lambda x: x[2], reverse=False)
            #print("Thread: " + str(thread_index) + " and Current Average: " + str(total_sum / total_elem_count))
            #print("Thread: " + str(thread_index) + " and Current Best: " + str(elem[0][2]))
            best.append(copy.deepcopy(elem[0]))
            #print("-----------------------------------------")
            total_sum = 0
            # save the best entry of this current thread for the current iteration
            #current_best_entries.append(elem[0])
            thread_index = thread_index + 1
        # save the last results of each thread
        #entries.append(copy.deepcopy(processed_list))
        #print("**********************************************")
        #print("**********************************************")
        #print("**********************************************")
        #print("Number of Iterations Done: ", (iteration_count + 1))
        #print("**********************************************")
        #print("**********************************************")
        #print("**********************************************")
        iteration_count = iteration_count + 1

    # All iterations are done
    # select the best results from the saved results of the iterations
    #best_result_list = []
    #for elem in entries:
    #    for pl in elem:
    #        sorted(pl, key=lambda x: x[2], reverse=False)
    #        for entry in pl:
    #            #best_result_list.append([entry[2], entry[1]])
    #            if entry[2] != INF:
    #                best_result_list.append(entry)

    #best_V2 = []
    #for elem in best:
    #    elem[0].insert(1, start_node)
    #    res = calculate_duration(permutation=elem[0], dist_data=DIST_DATA, VST=vehicles_start_times, M=M, Q=Q, load=LOAD,demand_dict=demand_dict, sn=start_node)
    #    best_V2.append(res)

    # sort the best results and get the first element as the solution
    best_result_list = sorted(best, key=lambda x: x[2], reverse=False)

    #print("BEST RESULT BELOW:")
    #print(best_result_list[0])

    best_route_max_time = best_result_list[0][2]
    best_route_sum_time = best_result_list[0][3]
    best_vehicle_routes = best_result_list[0][4]
    best_vehicle_times = best_result_list[0][5]


    #if best_vehicle_times is None:
    #    print("No feasible solution")
    #else:
     #   print(f"Best route max time: {best_route_max_time}")
     #   print(f"Best route sum time: {best_route_sum_time}")
     #   for vehicle_id, vehicle_cycles in best_vehicle_routes.items():
     #       print(f"Route of vehicle {vehicle_id}: {vehicle_cycles}")
     #   for vehicle_id, vehicle_time in best_vehicle_times.items():
     #       print(f"Time of vehicle {vehicle_id}: {vehicle_time}")

    end_time = datetime.now()
    exec_time = end_time - start_time
    #print(f"Time: {exec_time}")

    #print("END")



    print("Best route", best_route_max_time)
    print("Best sum time",best_route_sum_time)
    print("Best routes",best_vehicle_routes)
    print("Best vehicle times",best_vehicle_times)
    print("tsp exec time",exec_time)
    return (
        best_route_max_time,
        best_route_sum_time,
        best_vehicle_routes,
        best_vehicle_times,
        str(exec_time)
    )


if __name__ == '__main__':
    run(multithreaded=True)
