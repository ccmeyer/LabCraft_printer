#ifndef INC_PRESSURETRACERECORDER_H_
#define INC_PRESSURETRACERECORDER_H_

#include <cstdint>

enum class PressureTraceChannel : uint8_t {
  Print = 0,
  Refuel = 1
};

enum class PressureTraceEventType : uint8_t {
  TraceStart = 0,
  TraceStop,
  PulseStart,
  PulseEnd,
  QuietStart,
  QuietEnd,
  RecoveryStart,
  RecoveryEnd,
  ReadyEnter,
  ReadyExit
};

struct PressureTraceSample {
  uint16_t dtMs = 0;
  uint16_t rawPressure = 0;
  uint16_t controlPressure = 0;
  uint16_t avgPressure = 0;
  uint16_t target = 0;
  int16_t error = 0;
  int16_t dError = 0;
  uint16_t requestedHz = 0;
  uint16_t appliedHz = 0;
  uint8_t flags = 0;
  uint8_t ffBoostHzDiv16 = 0;
};

struct PressureTraceEvent {
  uint16_t dtMs = 0;
  uint8_t type = 0;
  uint8_t reserved = 0;
  uint16_t value0 = 0;
  uint16_t value1 = 0;
};

struct PressureTraceConfig {
  PressureTraceChannel channel = PressureTraceChannel::Print;
  uint16_t maxSamples = 512;
  uint16_t maxEvents = 192;
  uint16_t preRollMs = 100;
  uint16_t postRollMs = 150;
  bool includeAverage = true;
};

class PressureTraceRecorder {
public:
  static constexpr uint16_t kMaxSamples = 512;
  static constexpr uint16_t kMaxEvents = 192;

  static PressureTraceRecorder& instance();

  void configure(const PressureTraceConfig& cfg);
  void arm();
  void start(uint32_t tickMs);
  void stop(uint32_t tickMs);
  void reset();

  bool isArmed() const { return _armed; }
  bool isCapturing() const { return _capturing; }
  bool isComplete() const { return _complete; }

  void recordSample(PressureTraceChannel channel, const PressureTraceSample& sample);
  void recordEvent(PressureTraceChannel channel, const PressureTraceEvent& event);

  uint16_t sampleCount() const { return _sampleCount; }
  uint16_t eventCount() const { return _eventCount; }
  const PressureTraceSample* samples() const { return _samples; }
  const PressureTraceEvent* events() const { return _events; }
  const PressureTraceConfig& config() const { return _config; }
  uint32_t startTickMs() const { return _startTickMs; }

private:
  bool shouldRecordChannel(PressureTraceChannel channel) const {
    return channel == _config.channel;
  }

  PressureTraceConfig _config{};
  PressureTraceSample _samples[kMaxSamples]{};
  PressureTraceEvent _events[kMaxEvents]{};
  uint16_t _sampleCount = 0;
  uint16_t _eventCount = 0;
  uint32_t _startTickMs = 0;
  bool _armed = false;
  bool _capturing = false;
  bool _complete = false;
};

#endif /* INC_PRESSURETRACERECORDER_H_ */
