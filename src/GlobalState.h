   // GlobalState.h
   #ifndef GLOBALSTATE_H
   #define GLOBALSTATE_H

   enum SystemState {
       RUNNING,
       PAUSED
   };

   extern SystemState currentState;

   #endif // GLOBALSTATE_H