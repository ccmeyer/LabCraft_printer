#ifndef INC_DIAGNOSTICS_H_
#define INC_DIAGNOSTICS_H_

#include <cstddef>
#include <cstdint>

class Orchestrator;

struct PressureTraceCustomConfig {
    bool enabled = false;
    bool hasChannel = false;
    bool hasPressureMilliPsi = false;
    bool hasPulseUs = false;
    bool hasPulseCount = false;
    bool hasFrequencyHz = false;
    uint8_t channel = 0;
    uint16_t pressureMilliPsi = 0;
    uint16_t pulseUs = 0;
    uint16_t pulseCount = 0;
    uint16_t frequencyHz = 0;
};

struct DiagnosticsRequest {
    uint8_t seq8 = 0;
    uint32_t runId = 0;
    uint32_t timeoutMs = 0;
    bool fullProfile = false;
    bool runPressureDiagnostics = false;
    bool exportPressureTrace = false;
    uint16_t selectedPressureTraceTest = 0;
    uint16_t selectedDiagnosticId = 0;
    PressureTraceCustomConfig customPressureTrace{};
};

struct DiagnosticsSummary {
    uint16_t total = 0;
    uint16_t passed = 0;
    uint16_t failed = 0;
    bool aborted = false;
};

struct DiagnosticTestDescriptor {
    uint16_t testId;
    const char* name;
    const char* category;
    const char* profile;
    const char* gate;
};

class DiagnosticsRunner {
public:
    static DiagnosticsSummary runSelfTest(Orchestrator& orchestrator,
                                          const DiagnosticsRequest& request);
    static const DiagnosticTestDescriptor* registry(size_t* count);
};

#endif // INC_DIAGNOSTICS_H_
