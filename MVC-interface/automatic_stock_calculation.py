import itertools
from itertools import combinations_with_replacement

def find_minimal_stock_solutions_backtracking(target_concentrations, max_droplets):
    target_concentrations.sort()

    def can_achieve_all(stock_solutions):
        achievable_concentrations = {0: []}  # concentration -> list of (stock_solution, droplets)
        for num_droplets in range(1, max_droplets + 1):
            for comb in combinations_with_replacement(stock_solutions, num_droplets):
                total_concentration = sum(comb)
                if total_concentration not in achievable_concentrations:
                    achievable_concentrations[total_concentration] = comb
        return achievable_concentrations

    def backtrack(current_solutions, index):
        achievable_concentrations = can_achieve_all(current_solutions)

        if all(tc in achievable_concentrations for tc in target_concentrations):
            return current_solutions, achievable_concentrations

        if index == len(target_concentrations):
            return None, None

        # Explore both including and excluding the current concentration as a stock solution
        with_current, achievable_with = backtrack(current_solutions + [target_concentrations[index]], index + 1)
        without_current, achievable_without = backtrack(current_solutions, index + 1)

        if with_current is None:
            return without_current, achievable_without
        if without_current is None:
            return with_current, achievable_with
        
        # Prioritize the solution with fewer stock solutions
        if len(with_current) < len(without_current):
            return with_current, achievable_with
        elif len(with_current) > len(without_current):
            return without_current, achievable_without
        else:
            # If the number of stock solutions is the same, choose the one with the lower sum of concentrations
            if sum(with_current) < sum(without_current):
                return with_current, achievable_with
            else:
                return without_current, achievable_without

    minimal_solutions, achievable_concentrations = backtrack([], 0)
    return minimal_solutions, achievable_concentrations

def multi_reagent_optimization(reagents_data, max_total_droplets):
    reagent_solutions = []
    for target_concentrations, max_droplets in reagents_data:
        solutions = []
        for droplet_limit in range(1, max_droplets + 1):
            stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(target_concentrations, droplet_limit)
            max_droplets_for_any_concentration = max([len(achievable_concentrations[tc]) for tc in target_concentrations])
            solutions.append((stock_solutions, max_droplets_for_any_concentration))
        reagent_solutions.append(solutions)

    best_combination = None
    min_stock_count = float('inf')
    min_concentration_sum = float('inf')

    for combination in itertools.product(*reagent_solutions):
        stock_solution_set = set()
        total_droplets = 0
        max_droplets_per_reagent = []
        concentration_sum = 0

        for stock_solutions, droplets_used in combination:
            stock_solution_set.update(stock_solutions)
            total_droplets += droplets_used
            max_droplets_per_reagent.append(droplets_used)
            concentration_sum += sum(stock_solutions)  # Sum the concentrations used

        # Prioritize by fewest stock solutions, then by lowest concentration sum
        if total_droplets <= max_total_droplets:
            if len(stock_solution_set) < min_stock_count or (len(stock_solution_set) == min_stock_count and concentration_sum < min_concentration_sum):
                best_combination = combination
                min_stock_count = len(stock_solution_set)
                min_concentration_sum = concentration_sum

    if best_combination:
        final_stock_solutions = [sol[0] for sol in best_combination]
        max_droplets_per_reagent = [sol[1] for sol in best_combination]
    else:
        final_stock_solutions = []
        max_droplets_per_reagent = []

    return final_stock_solutions, max_droplets_per_reagent