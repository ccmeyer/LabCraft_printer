from itertools import combinations_with_replacement
import pandas as pd
import numpy as np

def check_stock_solutions(target_concentrations, stock_solutions, max_droplets):
    target_concentrations.sort()
    target_concentrations = [round(tc, 3) for tc in target_concentrations]
    unachievable_concentrations = []
    droplet_usage = {}

    achievable_concentrations = {0: []}  # concentration -> list of (stock_solution, droplets)
    
    # Generate all possible combinations of stock solutions within the max droplet count
    for num_droplets in range(1, max_droplets + 1):
        for comb in combinations_with_replacement(stock_solutions, num_droplets):
            total_concentration = sum(comb)
            if total_concentration not in achievable_concentrations:
                achievable_concentrations[total_concentration] = comb
    
    # Check which target concentrations are achievable and calculate droplet usage
    for tc in target_concentrations:
        if tc not in achievable_concentrations:
            unachievable_concentrations.append(tc)
        else:
            # Calculate the number of droplets used from each stock solution
            droplets = achievable_concentrations[tc]
            droplet_count = {stock: droplets.count(stock) for stock in stock_solutions}
            droplet_usage[tc] = droplet_count

    lookup_table = pd.DataFrame(droplet_usage).T.stack().reset_index().rename(columns={'level_0':'target_concentration', 'level_1':'stock_solution', 0:'droplet_count'})

    # Calculate the most droplets used for any target concentration
    if lookup_table.empty:
        max_droplets_for_any_concentration = 0
    else:
        max_droplets_for_any_concentration = lookup_table.groupby('target_concentration')['droplet_count'].sum().max()

    print(f'Max droplets for any concentration: {max_droplets_for_any_concentration}')
    # If there are unachievable concentrations, return them
    if unachievable_concentrations:
        return False, unachievable_concentrations, lookup_table, max_droplets_for_any_concentration
    else:
        return True, None, lookup_table, max_droplets_for_any_concentration

# Example usage:
# target_concentrations = [1/3,1,2,4,8,16,100]
target_concentrations = [1/3,100]
stock_solutions = [1, 5]  # User-provided stock concentrations
max_droplets = 10

feasible, unachievable, lookup_table, max_droplet_count = check_stock_solutions(target_concentrations, stock_solutions, max_droplets)

if feasible:
    print("All target concentrations can be achieved with the given stock solutions.")
    print("Droplet usage for each target concentration:")
    # for tc, usage in droplet_usage.items():
    #     print(f"  Target Concentration {tc}: {usage} droplets")
else:
    print(f"The following target concentrations cannot be achieved: {unachievable}")
    print("Droplet usage for achievable concentrations:")
    # for tc, usage in droplet_usage.items():
    #     print(f"  Target Concentration {tc}: {usage} droplets")

print(lookup_table)
