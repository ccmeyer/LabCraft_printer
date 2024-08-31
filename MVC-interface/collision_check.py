import json
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def save_boundaries_and_obstacles(boundaries, obstacles, filename):
    """
    Save the workspace boundaries and obstacles to a JSON file.
    
    Parameters:
    - boundaries: dictionary with keys 'min' and 'max', each containing dictionaries for the workspace boundaries.
    - obstacles: list of obstacles, where each obstacle is defined by a dictionary with keys 'corner1' and 'corner2'.
    - filename: the name of the file where the data will be saved.
    """
    data = {
        "boundaries": boundaries,
        "obstacles": obstacles
    }
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

def load_boundaries_and_obstacles(filename):
    """
    Load the workspace boundaries and obstacles from a JSON file.
    
    Parameters:
    - filename: the name of the file from which to load the data.
    
    Returns:
    - boundaries: dictionary with keys 'min' and 'max', each containing dictionaries for the workspace boundaries.
    - obstacles: list of obstacles, where each obstacle is defined by a dictionary with keys 'corner1' and 'corner2'.
    """
    with open(filename, 'r') as f:
        data = json.load(f)
    
    return data["boundaries"], data["obstacles"]

def check_collision(current_pos, target_pos, obstacles, boundaries):
    """
    Check if the path between the current and target positions collides with any obstacles or goes out of bounds.
    
    Parameters:
    - current_pos: dictionary representing the current position.
    - target_pos: dictionary representing the target position.
    - obstacles: list of obstacles, each defined by two corners.
    - boundaries: dictionary defining the workspace boundaries.
    
    Returns:
    - True if there is a collision, False otherwise.
    """
    # Boundary check
    for axis in ['X', 'Y', 'Z']:
        if not (boundaries['min'][axis] <= min(current_pos[axis], target_pos[axis]) and 
                max(current_pos[axis], target_pos[axis]) <= boundaries['max'][axis]):
            print(f"Path goes out of bounds on axis {axis}.")
            return True

    # Obstacle check
    for obstacle in obstacles:
        min_corner = {axis: min(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
        max_corner = {axis: max(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
        
        for axis in ['X', 'Y', 'Z']:
            min_proj = min(current_pos[axis], target_pos[axis])
            max_proj = max(current_pos[axis], target_pos[axis])
            
            if max_proj < min_corner[axis] or min_proj > max_corner[axis]:
                break
        else:
            print("Collision with obstacle detected.")
            return True

    return False

def plot_path_and_obstacles(current_pos, target_pos, obstacles, boundaries):
    """
    Plot the path, obstacles, and workspace boundaries in a 3D plot.
    
    Parameters:
    - current_pos: dictionary representing the current position.
    - target_pos: dictionary representing the target position.
    - obstacles: list of obstacles, each defined by two corners.
    - boundaries: dictionary defining the workspace boundaries.
    """
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # Plot the path
    path_x = [current_pos['X'], target_pos['X']]
    path_y = [current_pos['Y'], target_pos['Y']]
    path_z = [current_pos['Z'], target_pos['Z']]
    ax.plot(path_x, path_y, path_z, color='blue', label='Path')

    # Initialize plot limits
    all_x = path_x[:]
    all_y = path_y[:]
    all_z = path_z[:]

    # Plot the obstacles
    for obstacle in obstacles:
        min_corner = {axis: min(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
        max_corner = {axis: max(obstacle['corner1'][axis], obstacle['corner2'][axis]) for axis in ['X', 'Y', 'Z']}
        
        vertices = [
            [min_corner['X'], min_corner['Y'], min_corner['Z']],
            [max_corner['X'], min_corner['Y'], min_corner['Z']],
            [max_corner['X'], max_corner['Y'], min_corner['Z']],
            [min_corner['X'], max_corner['Y'], min_corner['Z']],
            [min_corner['X'], min_corner['Y'], max_corner['Z']],
            [max_corner['X'], min_corner['Y'], max_corner['Z']],
            [max_corner['X'], max_corner['Y'], max_corner['Z']],
            [min_corner['X'], max_corner['Y'], max_corner['Z']],
        ]

        faces = [
            [vertices[0], vertices[1], vertices[2], vertices[3]],
            [vertices[4], vertices[5], vertices[6], vertices[7]],
            [vertices[0], vertices[1], vertices[5], vertices[4]],
            [vertices[2], vertices[3], vertices[7], vertices[6]],
            [vertices[1], vertices[2], vertices[6], vertices[5]],
            [vertices[4], vertices[7], vertices[3], vertices[0]],
        ]

        ax.add_collection3d(Poly3DCollection(faces, facecolors='red', linewidths=1, edgecolors='r', alpha=.25))

        all_x.extend([min_corner['X'], max_corner['X']])
        all_y.extend([min_corner['Y'], max_corner['Y']])
        all_z.extend([min_corner['Z'], max_corner['Z']])

    # Plot the boundaries
    boundary_min = boundaries['min']
    boundary_max = boundaries['max']

    boundary_vertices = [
        [boundary_min['X'], boundary_min['Y'], boundary_min['Z']],
        [boundary_max['X'], boundary_min['Y'], boundary_min['Z']],
        [boundary_max['X'], boundary_max['Y'], boundary_min['Z']],
        [boundary_min['X'], boundary_max['Y'], boundary_min['Z']],
        [boundary_min['X'], boundary_min['Y'], boundary_max['Z']],
        [boundary_max['X'], boundary_min['Y'], boundary_max['Z']],
        [boundary_max['X'], boundary_max['Y'], boundary_max['Z']],
        [boundary_min['X'], boundary_max['Y'], boundary_max['Z']],
    ]

    boundary_faces = [
        [boundary_vertices[0], boundary_vertices[1], boundary_vertices[2], boundary_vertices[3]],
        [boundary_vertices[4], boundary_vertices[5], boundary_vertices[6], boundary_vertices[7]],
        [boundary_vertices[0], boundary_vertices[1], boundary_vertices[5], boundary_vertices[4]],
        [boundary_vertices[2], boundary_vertices[3], boundary_vertices[7], boundary_vertices[6]],
        [boundary_vertices[1], boundary_vertices[2], boundary_vertices[6], boundary_vertices[5]],
        [boundary_vertices[4], boundary_vertices[7], boundary_vertices[3], boundary_vertices[0]],
    ]

    ax.add_collection3d(Poly3DCollection(boundary_faces, facecolors='green', linewidths=1, edgecolors='g', alpha=.1))

    all_x.extend([boundary_min['X'], boundary_max['X']])
    all_y.extend([boundary_min['Y'], boundary_max['Y']])
    all_z.extend([boundary_min['Z'], boundary_max['Z']])

    # Set limits for the plot
    ax.set_xlim([min(all_x), max(all_x)])
    ax.set_ylim([min(all_y), max(all_y)])
    ax.set_zlim([max(all_z), min(all_z)])  # Invert Z-axis

    # Set labels and show the plot
    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.legend()
    plt.show()

# Example usage:
current_position = {'X': 500, 'Y': 500, 'Z': 500}
target_position = {'X': 4500, 'Y': 8500, 'Z': 500}

# Define the boundaries of the machine workspace
boundaries = {
    'min': {'X': 0, 'Y': 0, 'Z': 0},
    'max': {'X': 12600, 'Y': 11000, 'Z': 31000}
}

obstacles = [
    {'name':'rack','corner1': {'X': 2400, 'Y': 0, 'Z': 2500}, 'corner2': {'X': 0, 'Y': 11000, 'Z': 31000}},
    {'name':'left_balance_post','corner1': {'X': 5400, 'Y': 3000, 'Z': 0}, 'corner2': {'X': 12600, 'Y': 0, 'Z': 31000}},
    {'name':'right_front_balance_post','corner1': {'X': 5400, 'Y': 4500, 'Z': 0}, 'corner2': {'X': 12600, 'Y': 9500, 'Z': 31000}},
    {'name':'right_back_balance_post','corner1': {'X': 11500, 'Y': 5300, 'Z': 0}, 'corner2': {'X': 12600, 'Y': 9500, 'Z': 31000}}
]
# rack = ((2400, 0, 2500), (0, 11000, 31000))
# left_balance_post = ((5400, 3000, 0), (12600, 0, 31000))
# right_front_balance_post = ((5400, 4500, 0), (11000, 9500, 31000))
# right_back_balance_post = ((11500, 5300, 0), (12600, 9500, 31000))

collision = check_collision(current_position, target_position, obstacles, boundaries)
print("Collision detected:", collision)

# Plot the path and obstacles
plot_path_and_obstacles(current_position, target_position, obstacles, boundaries)

# Save to a JSON file
save_boundaries_and_obstacles(boundaries, obstacles, 'workspace_and_obstacles.json')

# Load from a JSON file
loaded_boundaries, loaded_obstacles = load_boundaries_and_obstacles('workspace_and_obstacles.json')
print("Loaded boundaries:", loaded_boundaries)
print("Loaded obstacles:", loaded_obstacles)
