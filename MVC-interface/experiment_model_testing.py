from PySide6 import QtCore
import pandas as pd

class ReactionComposition:
    def __init__(self, name):
        self.name = name
        self.reagents = {}  # Dictionary to hold reagent name and its target concentration

    def add_reagent(self, reagent_name, concentration):
        """Add a reagent and its target concentration to the reaction."""
        self.reagents[reagent_name] = concentration

    def remove_reagent(self, reagent_name):
        """Remove a reagent from the reaction."""
        if reagent_name in self.reagents:
            del self.reagents[reagent_name]
        else:
            raise ValueError(f"Reagent '{reagent_name}' not found in this reaction.")

    def get_concentration(self, reagent_name):
        """Get the target concentration of a reagent in this reaction."""
        return self.reagents.get(reagent_name, None)

    def get_all_reagents(self):
        """Get all reagents and their concentrations in this reaction."""
        return self.reagents

    def __eq__(self, other):
        """Equality check to ensure unique reactions."""
        if not isinstance(other, ReactionComposition):
            return False
        return self.reagents == other.reagents

    def __hash__(self):
        """Hash function to allow use in sets and dictionaries."""
        return hash(frozenset(self.reagents.items()))

class ReactionCollection:
    def __init__(self):
        self.reactions = {}  # Dictionary to hold ReactionComposition objects by name

    def add_reaction(self, reaction):
        """Add a unique reaction to the collection."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must add a ReactionComposition object.")
        if reaction.name not in self.reactions:
            self.reactions[reaction.name] = reaction
        else:
            raise ValueError(f"Reaction '{reaction.name}' already exists in the collection.")

    def remove_reaction(self, name):
        """Remove a reaction from the collection by its name."""
        if name in self.reactions:
            del self.reactions[name]
        else:
            raise ValueError(f"Reaction '{name}' not found in the collection.")

    def get_reaction(self, name):
        """Get a reaction by its name."""
        return self.reactions.get(name, None)

    def get_all_reactions(self):
        """Get all reactions in the collection."""
        return list(self.reactions.values())

    def find_duplicate(self, reaction):
        """Check if a similar reaction already exists in the collection."""
        for existing_reaction in self.reactions.values():
            if existing_reaction == reaction:
                return True
        return False
    
class Well:
    def __init__(self, well_id):
        self.well_id = well_id  # Unique identifier for the well (e.g., "A1", "B2")
        self.row = well_id[0]  # Row of the well (e.g., "A", "B")
        self.col = int(well_id[1:])  # Column of the well (e.g., 1, 2)
        self.assigned_reaction = None  # The reaction assigned to this well
        self.printed_droplets = {}  # Track the number of droplets printed for each reagent
        self.timestamp = None  # Timestamp when the well was last printed

    def assign_reaction(self, reaction):
        """Assign a reaction to the well."""
        if not isinstance(reaction, ReactionComposition):
            raise ValueError("Must assign a ReactionComposition object.")
        self.assigned_reaction = reaction

    def record_droplet(self, reagent_name, count):
        """Record the number of droplets printed for a specific reagent."""
        if reagent_name in self.printed_droplets:
            self.printed_droplets[reagent_name] += count
        else:
            self.printed_droplets[reagent_name] = count
        self.timestamp = QtCore.QDateTime.currentDateTime().toString(QtCore.Qt.ISODate)

    def get_status(self):
        """Get the status of the well."""
        return {
            "reaction": self.assigned_reaction.name if self.assigned_reaction else None,
            "printed_droplets": self.printed_droplets,
            "timestamp": self.timestamp,
        }

    def clear(self):
        """Clear the well's assigned reaction and status."""
        self.assigned_reaction = None
        self.printed_droplets.clear()
        self.timestamp = None

class WellPlate:
    def __init__(self, plate_format):
        self.plate_format = plate_format  # '96', '384', '1536'
        self.wells = self.create_wells()
        self.excluded_wells = set()

    def create_wells(self):
        """Create wells based on the plate format."""
        wells = []
        if self.plate_format == '96':
            rows = 'ABCDEFGH'
            cols = range(1, 13)
        elif self.plate_format == '384':
            rows = [chr(i) for i in range(65, 81)]  # A-P
            cols = range(1, 25)
        elif self.plate_format == '1536':
            rows = [chr(i) for i in range(65, 81)]  # A-P
            cols = range(1, 49)
        else:
            raise ValueError("Invalid plate format")

        for row in rows:
            for col in cols:
                well_id = f"{row}{col}"
                wells.append(Well(well_id))

        return wells

    def _get_plate_dimensions(self, format):
        """Return the dimensions (rows, cols) based on the plate format."""
        if format == "96":
            return 8, 12
        elif format == "384":
            return 16, 24
        elif format == "1536":
            return 32, 48
        else:
            raise ValueError("Unsupported plate format. Use '96', '384', or '1536'.")

    def exclude_well(self, well_id):
        """Exclude a well from being used."""
        if well_id in self.wells:
            self.excluded_wells.add(well_id)
        else:
            raise ValueError(f"Well '{well_id}' does not exist in the plate.")

    def include_well(self, well_id):
        """Include an excluded well back into use."""
        self.excluded_wells.discard(well_id)

    def assign_reaction_to_well(self, well_id, reaction):
        """Assign a reaction to a specific well."""
        if well_id in self.wells and well_id not in self.excluded_wells:
            self.wells[well_id].assign_reaction(reaction)
        else:
            raise ValueError(f"Cannot assign reaction to well '{well_id}'. It may be excluded or does not exist.")

    def get_well(self, well_id):
        """Retrieve a specific well by its ID."""
        return self.wells.get(well_id, None)

    def get_available_wells(self, fill_by="rows"):
        """
        Get a list of available wells, sorted by rows or columns.

        Args:
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            list of Well: Sorted list of available wells.
        """
        if fill_by not in ["rows", "columns"]:
            raise ValueError("fill_by must be 'rows' or 'columns'.")

        available_wells = [well for well in self.wells if well not in self.excluded_wells and well.assigned_reaction is None]

        if fill_by == "rows":
            available_wells.sort(key=lambda w: (w.row, w.col))
        else:  # fill_by == "columns"
            available_wells.sort(key=lambda w: (w.col, w.row))

        return available_wells
    
    def get_all_wells(self):
        """Get a list of all wells."""
        return list(self.wells.values())

    def clear_all_wells(self):
        """Clear all wells and reset their status."""
        for well in self.wells:
            well.clear()

    def get_plate_status(self):
        """Get the status of the entire well plate."""
        status = {}
        for well_id, well in self.wells.items():
            status[well_id] = well.get_status()
        return status

    def assign_reactions_to_wells(self, reactions, fill_by="columns"):
        """
        Systematically assign reactions to available wells.

        Args:
            reactions (list of ReactionComposition): The reactions to assign to wells.
            fill_by (str): Whether to fill wells by "rows" or "columns".

        Returns:
            dict: A dictionary mapping reaction names to well IDs.
        """
        available_wells = self.get_available_wells(fill_by=fill_by)
        reaction_assignment = {}

        if len(reactions) > len(available_wells):
            raise ValueError("Not enough available wells to assign all reactions.")

        for i, reaction in enumerate(reactions):
            well = available_wells[i]
            well.assign_reaction(reaction)
            reaction_assignment[reaction.name] = well.well_id
            print(f"Assigned reaction '{reaction.name}' to well '{well.well_id}'.")

        return reaction_assignment


def load_reactions_from_csv(csv_file_path):
    """
    Load reactions from a CSV file and return a ReactionCollection.
    
    The CSV should have a 'reaction_id' column followed by columns for each reagent with target concentrations.
    """
    df = pd.read_csv(csv_file_path)
    reaction_collection = ReactionCollection()

    for _, row in df.iterrows():
        reaction_name = row['reaction_id']
        reaction = ReactionComposition(reaction_name)

        for reagent_name, concentration in row.items():
            if reagent_name != 'reaction_id':  # Skip the 'reaction_id' column
                reaction.add_reagent(reagent_name, concentration)
        
        reaction_collection.add_reaction(reaction)

    return reaction_collection

# Example usage:
csv_file_path = "mock_reaction_compositions.csv"  # Path to the CSV file
reaction_collection = load_reactions_from_csv(csv_file_path)

# Now we can assign these reactions to a well plate
well_plate = WellPlate(plate_format='96')  # Creating a 96-well plate
reactions = reaction_collection.get_all_reactions()  # Get all reactions from the collection

# Assign the reactions to the well plate, filling by rows or columns
reaction_assignment = well_plate.assign_reactions_to_wells(reactions, fill_by="columns")

# Printing the assignment
for reaction_name, well_id in reaction_assignment.items():
    print(f"Reaction '{reaction_name}' assigned to well {well_id}")