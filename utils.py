

def section_break():
    print("\n==================================================================\n")
    return

def print_title(title):
    section_break()
    print(title)
    section_break()
    return

def select_options(lst,message='Select one of the options:', trim=False):
    if len(lst) == 0:
        print('No options to select')
        return
    if trim:
        simple_paths = []
        for l in lst:
            if l.replace('\\','/').split('/')[-1] == '':
                simple_paths.append(l.replace('\\','/').split('/')[-2])
            else:
                simple_paths.append(l.replace('\\','/').split('/')[-1])
    else:
        simple_paths = lst
    exit_option = 'Exit'
    lst.append(exit_option)
    simple_paths.append(exit_option)

    for index,opt in enumerate(simple_paths):
        print(index,opt)
    enteredStr = input(message)
    while not enteredStr.isnumeric() or int(enteredStr) >= len(lst) or int(enteredStr) < 0:
        enteredStr = input("The entered command is invalid. Please enter a valid index: ")
    print('Option selected: ',lst[int(enteredStr)],'\n')
    if lst[int(enteredStr)] == exit_option:
        quit = True
    else:
        quit = False
    return lst[int(enteredStr)],quit

def ask_for_number(message='Enter number: '):
    try:
        return float(input(message))

    except:
        print('Not a valid input')
        return ask_for_number()
