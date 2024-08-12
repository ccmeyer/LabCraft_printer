import heapq
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

import numpy as np

class Workspace:
    def __init__(self, min_x, max_x, min_y, max_y, min_z, max_z):
        self.min_x = min_x
        self.max_x = max_x
        self.min_y = min_y
        self.max_y = max_y
        self.min_z = min_z
        self.max_z = max_z

    def is_within_bounds(self, x, y, z):
        """Check if a point is within the workspace boundaries."""
        return (self.min_x <= x <= self.max_x and
                self.min_y <= y <= self.max_y and
                self.min_z <= z <= self.max_z)

class Obstacle:
    def __init__(self, min_x, max_x, min_y, max_y, min_z, max_z):
        self.min_x = min_x
        self.max_x = max_x
        self.min_y = min_y
        self.max_y = max_y
        self.min_z = min_z
        self.max_z = max_z

    def contains_point(self, x, y, z):
        """Check if a point is inside the obstacle."""
        return (self.min_x <= x <= self.max_x and
                self.min_y <= y <= self.max_y and
                self.min_z <= z <= self.max_z)
    
    def plot(self, ax):
            """Plot an obstacle as a filled cuboid."""
            # Create the vertices of a cuboid
            x = [self.min_x, self.max_x]
            y = [self.min_y, self.max_y]
            z = [self.min_z, self.max_z]
            
            # Generate the list of vertices for each rectangle
            vertices = np.array([[x[0], y[0], z[0]],
                                [x[0], y[1], z[0]],
                                [x[1], y[1], z[0]],
                                [x[1], y[0], z[0]],
                                [x[0], y[0], z[1]],
                                [x[0], y[1], z[1]],
                                [x[1], y[1], z[1]],
                                [x[1], y[0], z[1]]])

            # Create sides of the cuboid
            faces = [[vertices[j] for j in [0, 1, 5, 4]],
                    [vertices[j] for j in [7, 6, 2, 3]],
                    [vertices[j] for j in [0, 3, 7, 4]],
                    [vertices[j] for j in [1, 2, 6, 5]],
                    [vertices[j] for j in [7, 4, 5, 6]],
                    [vertices[j] for j in [0, 1, 2, 3]]]

            # Plot each side
            poly = Poly3DCollection(faces, facecolors='red', linewidths=1, edgecolors='r', alpha=.25)
            ax.add_collection3d(poly)

class Node:
    """Represents a node in the pathfinding process."""
    def __init__(self, position, parent=None, direction=None, g=0, h=0):
        self.position = position
        self.parent = parent
        self.direction = direction
        self.g = g
        self.h = h
        self.f = g + h

    def __lt__(self, other):
        return self.f < other.f

def heuristic(a, b):
    """Calculate the Manhattan distance for a heuristic in 3D space."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])

def directional_heuristic(current_node, neighbor_position, target):
    """Calculate cost considering potential directional changes."""
    direction_change_cost = 100
    straight_cost = heuristic(neighbor_position, target)
    print("Straight Cost:",straight_cost)
    if current_node and current_node.direction:
        new_direction = (neighbor_position[0] - current_node.position[0],
                         neighbor_position[1] - current_node.position[1],
                         neighbor_position[2] - current_node.position[2])
        if new_direction != current_node.direction:
            return straight_cost + direction_change_cost
    return straight_cost

def a_star(start, target, obstacles, workspace, grid_size=1):
    """Perform the A* algorithm accounting for workspace and minimizing direction changes."""
    # round the start and target to the nearest grid point
    original_start = start
    start = (round(start[0] / grid_size) * grid_size,
             round(start[1] / grid_size) * grid_size,
             round(start[2] / grid_size) * grid_size)
    original_target = target
    target = (round(target[0] / grid_size) * grid_size,
              round(target[1] / grid_size) * grid_size,
              round(target[2] / grid_size) * grid_size)
    open_set = []
    closed_set = set()
    start_node = Node(start, None, None, 0, heuristic(start, target))
    heapq.heappush(open_set, start_node)

    while open_set:
        current_node = heapq.heappop(open_set)
        closed_set.add(current_node.position)

        if current_node.position == target:
            path = []
            while current_node:
                path.append(current_node.position)
                current_node = current_node.parent
            full_path = path[::-1]
            # change the last point to the original target
            full_path[-1] = original_target

            return full_path

        for d in [(grid_size, 0, 0), (-grid_size, 0, 0), (0, grid_size, 0), (0, -grid_size, 0), (0, 0, grid_size), (0, 0, -grid_size)]:
            neighbor_pos = (current_node.position[0] + d[0], current_node.position[1] + d[1], current_node.position[2] + d[2])
            if neighbor_pos in closed_set or not workspace.is_within_bounds(*neighbor_pos) or any(ob.contains_point(*neighbor_pos) for ob in obstacles):
                continue

            new_g = current_node.g + grid_size
            new_h = directional_heuristic(current_node, neighbor_pos, target)
            new_f = new_g + new_h
            neighbor_node = Node(neighbor_pos, current_node, d, new_g, new_h)

            if all(neighbor_node.position != n.position or new_f < n.f for n in open_set):
                heapq.heappush(open_set, neighbor_node)

    return None  # If no path is found

def extract_waypoints(full_path):
    """Extract waypoints from the full path where the direction changes."""
    if not full_path:
        return []

    waypoints = [full_path[0]]  # Start with the initial position
    last_direction = None

    for i in range(1, len(full_path)):
        current_direction = (
            full_path[i][0] - full_path[i - 1][0],
            full_path[i][1] - full_path[i - 1][1],
            full_path[i][2] - full_path[i - 1][2]
        )

        # Check if direction has changed since last waypoint
        if current_direction != last_direction:
            waypoints.append(full_path[i - 1])
            last_direction = current_direction

    # Always add the last point of the path
    if full_path[-1] != waypoints[-1]:
        waypoints.append(full_path[-1])

    return waypoints

def visualize_path_and_obstacles(path, obstacles):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')

    # Plot each obstacle
    for obs in obstacles:
        obs.plot(ax)

    # Plot path
    if path:
        waypoints = np.array(path)
        ax.plot(waypoints[:, 0], waypoints[:, 1], waypoints[:, 2], 'o-', label='Path')

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.legend()
    plt.show()

# Example usage:
workspace = Workspace(0, 40, 0, 40, 0, 40)
obstacles = [
    Obstacle(0, 10, 10, 20, 0, 40),
    Obstacle(30, 40, 10, 20, 0, 40),
    Obstacle(0, 40, 20, 30, 0, 20),
]
start = (0, 0, 4)
target = (40, 39, 24)
path = a_star(start, target, obstacles, workspace,grid_size=10)

waypoints = extract_waypoints(path)
visualize_path_and_obstacles(waypoints, obstacles)

print("Optimized Path:", path)
print("Waypoints:", waypoints)
