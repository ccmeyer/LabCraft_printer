from itertools import combinations_with_replacement, product

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

        print(f"Current solutions: {current_solutions}")
        
        with_current, achievable_with = backtrack(current_solutions + [target_concentrations[index]], index + 1)
        without_current, achievable_without = backtrack(current_solutions, index + 1)

        if with_current is None:
            return without_current, achievable_without
        if without_current is None:
            return with_current, achievable_with
        return (with_current, achievable_with) if len(with_current) < len(without_current) else (without_current, achievable_without)

    minimal_solutions, achievable_concentrations = backtrack([], 0)
    
    print(f"Minimal solutions found: {minimal_solutions}")
    print(f"Achievable concentrations: {achievable_concentrations}")
    
    return minimal_solutions, achievable_concentrations

def multi_reagent_optimization(reagents_data, max_total_droplets):
    """
    Optimize stock solutions across multiple reagents.

    reagents_data: list of (target_concentrations, max_droplets) tuples, one for each reagent.
    max_total_droplets: The maximum total droplets allowed per well.

    Returns: The optimal stock solution set for each reagent and the total droplets used.
    """
    # Step 1: Optimize stock solutions for each reagent separately
    reagent_solutions = []
    for target_concentrations, max_droplets in reagents_data:
        solutions = []
        for droplet_limit in range(1, max_droplets + 1):
            stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(target_concentrations, droplet_limit)
            max_droplets_for_any_concentration = max([len(achievable_concentrations[tc]) for tc in target_concentrations])
            print(f"Droplet limit: {droplet_limit}, Stock solutions: {stock_solutions}, Max droplets needed for any concentration: {max_droplets_for_any_concentration}")
            solutions.append((stock_solutions, max_droplets_for_any_concentration))
        reagent_solutions.append(solutions)

    # Step 2: Combine the stock solutions across all reagents while minimizing total droplets and number of stocks
    best_combination = None
    min_stock_count = float('inf')
    max_droplet_usage = 0

    # Iterate over all combinations of stock solutions for each reagent
    for combination in product(*reagent_solutions):
        stock_solution_set = set()
        total_droplets = 0

        for stock_solutions, droplets_used in combination:
            stock_solution_set.update(stock_solutions)
            total_droplets += droplets_used

        print(f"Combination: {combination}, Stock solutions set: {stock_solution_set}, Total droplets: {total_droplets}")

        if total_droplets <= max_total_droplets:
            if len(stock_solution_set) < min_stock_count or (len(stock_solution_set) == min_stock_count and total_droplets > max_droplet_usage):
                best_combination = combination
                min_stock_count = len(stock_solution_set)
                max_droplet_usage = total_droplets
                print(f"New best combination found: {best_combination}, Stock count: {min_stock_count}, Droplets used: {max_droplet_usage}")

    # Extract the best stock solutions and total droplet usage
    if best_combination:
        final_stock_solutions = [sol[0] for sol in best_combination]
        total_droplets_used = sum([sol[1] for sol in best_combination])
    else:
        final_stock_solutions = []
        total_droplets_used = 0

    return final_stock_solutions, total_droplets_used

# Example usage
target_concentrations = [
    ([0.5, 2, 4, 5,8], 5),
    ([2, 4,6], 5),
    ([1, 2, 4,6], 5),
    ([1, 2, 4,6], 5),
    ([1], 5)
]

max_total_droplets = 20
final_stock_solutions, total_droplets_used = multi_reagent_optimization(target_concentrations, max_total_droplets)
print(f"Final Stock solutions needed: {final_stock_solutions}")
print(f"Total droplets used: {total_droplets_used}")


# target_concentrations = [1, 2, 3]
# max_droplets = 5

# stock_solutions, achievable_concentrations = find_minimal_stock_solutions_backtracking(target_concentrations, max_droplets)

# print(f"\nFinal Stock solutions needed: {stock_solutions}")
# print("Droplet breakdown to achieve target concentrations:")

# for tc in target_concentrations:
#     if tc in achievable_concentrations:
#         droplet_combination = achievable_concentrations[tc]
#         breakdown = {stock: droplet_combination.count(stock) for stock in stock_solutions}
#         print(f"  To achieve {tc}: {breakdown} (Total droplets: {len(droplet_combination)})")
#     else:
#         print(f"  Cannot achieve {tc} with the given stock solutions.")
