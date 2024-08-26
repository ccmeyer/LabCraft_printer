#ifndef TASKCOMMAND_H
#define TASKCOMMAND_H

#include <functional>
#include <queue>
#include <vector>

// Task struct to represent a scheduled task
struct Task {
    std::function<void()> function;       // Function pointer to the task's function
    unsigned long nextExecutionTime;      // The next time the task should run

    Task(std::function<void()> func, unsigned long execTime)
        : function(func), nextExecutionTime(execTime) {}
};

// Task queue to manage scheduled tasks
class TaskQueue {
public:
    void addTask(const Task& task);       // Add a task to the queue
    void removeTask();                    // Remove the next task from the queue
    void executeNextTask();               // Execute the next task in the queue
    bool isEmpty() const;                 // Check if the queue is empty

private:
    // Custom comparator for priority queue (sorted by nextExecutionTime)
    struct CompareTask {
        bool operator()(const Task& t1, const Task& t2) {
            return t1.nextExecutionTime > t2.nextExecutionTime; // Earlier tasks have higher priority
        }
    };

    std::priority_queue<Task, std::vector<Task>, CompareTask> taskQueue;  // Priority queue to store tasks
};

// enum CommandType {
//     OPEN_GRIPPER,
//     CLOSE_GRIPPER,
//     GRIPPER_OFF,
//     // Add more command types as needed
// };

// /**
//  * @brief Represents a command with associated parameters.
//  */
// struct Command {
//   int commandNum; /**< The command number. */
//   CommandType type; /**< The type of command. */
//   long param1; /**< The first parameter. */
//   long param2; /**< The second parameter. */
//   long param3; /**< The third parameter. */
  
//   /**
//    * @brief Constructs a Command object with the specified parameters.
//    * @param num The command number.
//    * @param t The type of command.
//    * @param p1 The first parameter.
//    * @param p2 The second parameter.
//    * @param p3 The third parameter.
//    */
//   Command(int num, CommandType t, long p1, long p2, long p3) : 
//     commandNum(num), type(t), param1(p1), param2(p2), param3(p3) {}
// };

// CommandType commandType;

// enum State {
//     FREE,
//     MOVING_XYZ,
//     CHANGING_PRESSURE,
//     PRINTING,
//     HOMING_AXIS,
//     PUMPING,
//     WAITING,
//     PAUSED
//     // Add more states as needed
// };

// // Command queue
// std::queue<Command> commandQueue;

// // Current state
// State currentState = FREE;

// // Function to map command names to command types
// CommandType mapCommandType(const char* commandName) {
//     if (strcmp(commandName, "RELATIVE_XYZ") == 0) {
//         return RELATIVE_XYZ;
//     } else {
//         return UNKNOWN;
//     }
// }

#endif // TASKCOMMAND_H
