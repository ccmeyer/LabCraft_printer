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

    pinMode(pumpValvePin1, OUTPUT);
    digitalWrite(pumpValvePin1,LOW);
    
    pinMode(pumpValvePin2, OUTPUT);
    digitalWrite(pumpValvePin2,LOW);

    pinMode(printValvePin, OUTPUT);
    digitalWrite(printValvePin,LOW);

    pinMode(gatePin, OUTPUT);
    digitalWrite(gatePin,LOW);

    // Setup imaging pins
    pinMode(flashPin, OUTPUT);
    digitalWrite(flashPin,LOW);

    pinMode(cameraPin, INPUT);

    pinMode(xstop, INPUT);
    pinMode(ystop, INPUT);
    pinMode(zstop, INPUT);
    pinMode(pstop, INPUT);
}

void blinkLED()
{
    digitalWrite(ledPin, HIGH);
    delay(500);
    digitalWrite(ledPin, LOW);
    delay(500);
}
