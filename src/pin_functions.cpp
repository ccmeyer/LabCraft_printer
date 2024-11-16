#include "pin_functions.h"

void setupPins()
{
    pinMode(ledPin, OUTPUT);
    digitalWrite(ledPin,LOW);

    pinMode(printPin, OUTPUT);
    digitalWrite(printPin,LOW);

    // Setup gripper pins
    pinMode(pumpPin, OUTPUT);
    digitalWrite(pumpPin,LOW);

    pinMode(pumpValvePin, OUTPUT);
    digitalWrite(pumpValvePin,LOW);
    
    // pinMode(pumpValvePin2, OUTPUT);
    // digitalWrite(pumpValvePin2,LOW);

    pinMode(printValvePin, OUTPUT);
    digitalWrite(printValvePin,LOW);

    pinMode(refuelValvePin, OUTPUT);
    digitalWrite(refuelValvePin,LOW);

    pinMode(xstop, INPUT);
    pinMode(ystop, INPUT);
    pinMode(zstop, INPUT);
    pinMode(pstop, INPUT);
    pinMode(rstop, INPUT);
}

void blinkLED()
{
    digitalWrite(ledPin, HIGH);
    delay(500);
    digitalWrite(ledPin, LOW);
    delay(500);
}
