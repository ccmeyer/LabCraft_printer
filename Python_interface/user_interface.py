import customtkinter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import customtkinter as ctk



class MyCheckboxFrame(customtkinter.CTkFrame):
    def __init__(self, master, title, values):
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        self.values = values
        self.title = title
        self.checkboxes = []

        self.title = customtkinter.CTkLabel(self, text=self.title, fg_color="gray30", corner_radius=6)
        self.title.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")

        for i, value in enumerate(self.values):
            checkbox = customtkinter.CTkCheckBox(self, text=value)
            checkbox.grid(row=i+1, column=0, padx=10, pady=(10, 0), sticky="w")
            self.checkboxes.append(checkbox)

    def get(self):
        checked_checkboxes = []
        for checkbox in self.checkboxes:
            if checkbox.get() == 1:
                checked_checkboxes.append(checkbox.cget("text"))
        return checked_checkboxes
    
class MyRadiobuttonFrame(customtkinter.CTkFrame):
    def __init__(self, master, title, values):
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        self.values = values
        self.title = title
        self.radiobuttons = []
        self.variable = customtkinter.StringVar(value="")

        self.title = customtkinter.CTkLabel(self, text=self.title, fg_color="gray30", corner_radius=6)
        self.title.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")

        for i, value in enumerate(self.values):
            radiobutton = customtkinter.CTkRadioButton(self, text=value, value=value, variable=self.variable)
            radiobutton.grid(row=i + 1, column=0, padx=10, pady=(10, 0), sticky="w")
            self.radiobuttons.append(radiobutton)

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)
import numpy as np

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Keyboard Shortcuts")
        self.geometry("200x200")
        # ... rest of your code ...

        # Bind the function self.on_key_press to the key press event
        self.bind("<Key>", self.on_key_press)

    def on_key_press(self, event):
        # The keysym attribute contains the name of the special key that was pressed
        if event.keysym == "Up":
            print("Up arrow key pressed")
        elif event.keysym == "Down":
            print("Down arrow key pressed")
        elif event.keysym == "Left":
            print("Left arrow key pressed")
        elif event.keysym == "Right":
            print("Right arrow key pressed")
        elif event.keysym == "BackSpace":
            print("Backspace key pressed")
        elif event.keysym == "Escape":
            print("Escape key pressed")
        else:
            print("Key pressed:", event.char)

# class App(ctk.CTk):
#     def __init__(self):
#         super().__init__()

#         # ... rest of your code ...

#         # Matplotlib figure
#         self.fig = plt.Figure(figsize=(5, 4), dpi=100)
#         self.plot = self.fig.add_subplot(111)
#         self.x = np.linspace(0, 2*np.pi, 100)
#         self.y = np.sin(self.x)
#         self.line, = self.plot.plot(self.x, self.y)

#         # Adding the Matplotlib figure to Tkinter
#         self.canvas = FigureCanvasTkAgg(self.fig, master=self)  
#         self.canvas.draw()
#         self.canvas.get_tk_widget().grid(row=1, column=0, padx=10, pady=10, sticky="nsew", columnspan=2)

#         # Schedule the update function to be called after 1000 milliseconds
#         self.after(1000, self.update_plot)

#     def update_plot(self):
#         # Update the y data of the line
#         self.x += 0.1
#         self.y = np.sin(self.x)
#         self.line.set_ydata(self.y)

#         # Redraw the canvas
#         self.canvas.draw()

#         # Schedule the update function to be called again after 1000 milliseconds
#         self.after(10, self.update_plot)
        
# class App(ctk.CTk):
#     def __init__(self):
#         super().__init__()

#         self.title("my app")
#         self.geometry("400x400")
#         self.grid_columnconfigure((0, 1), weight=1)
#         self.grid_rowconfigure((0, 1), weight=1)

#         self.checkbox_frame = MyCheckboxFrame(self, "Values", values=["value 1", "value 2", "value 3"])
#         self.checkbox_frame.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="nsew")
#         self.radiobutton_frame = MyRadiobuttonFrame(self, "Options", values=["option 1", "option 2"])
#         self.radiobutton_frame.grid(row=0, column=1, padx=(0, 10), pady=(10, 0), sticky="nsew")

#         self.button = ctk.CTkButton(self, text="my button", command=self.button_callback)
#         self.button.grid(row=3, column=0, padx=10, pady=10, sticky="ew", columnspan=2)

#         # Matplotlib figure
#         self.fig = plt.Figure(figsize=(5, 4), dpi=100)
#         self.plot = self.fig.add_subplot(111)
#         self.plot.plot([1, 2, 3, 4, 5], [1, 2, 3, 4, 10])

#         # Adding the Matplotlib figure to Tkinter
#         self.canvas = FigureCanvasTkAgg(self.fig, master=self)  
#         self.canvas.draw()
#         self.canvas.get_tk_widget().grid(row=1, column=0, padx=10, pady=10, sticky="nsew", columnspan=2)

#     def button_callback(self):
#         print("checkbox_frame:", self.checkbox_frame.get())
#         print("radiobutton_frame:", self.radiobutton_frame.get())

# class App(customtkinter.CTk):
#     def __init__(self):
#         super().__init__()

#         self.title("my app")
#         self.geometry("400x220")
#         self.grid_columnconfigure((0, 1), weight=1)
#         self.grid_rowconfigure(0, weight=1)

#         self.checkbox_frame = MyCheckboxFrame(self, "Values", values=["value 1", "value 2", "value 3"])
#         self.checkbox_frame.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="nsew")
#         self.radiobutton_frame = MyRadiobuttonFrame(self, "Options", values=["option 1", "option 2"])
#         self.radiobutton_frame.grid(row=0, column=1, padx=(0, 10), pady=(10, 0), sticky="nsew")

#         self.button = customtkinter.CTkButton(self, text="my button", command=self.button_callback)
#         self.button.grid(row=3, column=0, padx=10, pady=10, sticky="ew", columnspan=2)

#     def button_callback(self):
#         print("checkbox_frame:", self.checkbox_frame.get())
#         print("radiobutton_frame:", self.radiobutton_frame.get())

app = App()
app.mainloop()