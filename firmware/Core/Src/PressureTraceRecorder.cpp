#include "PressureTraceRecorder.h"

PressureTraceRecorder& PressureTraceRecorder::instance() {
  static PressureTraceRecorder recorder;
  return recorder;
}

void PressureTraceRecorder::configure(const PressureTraceConfig& cfg) {
  _config = cfg;
  if (_config.maxSamples > kMaxSamples) _config.maxSamples = kMaxSamples;
  if (_config.maxEvents > kMaxEvents) _config.maxEvents = kMaxEvents;
  if (_config.sampleStride == 0u) _config.sampleStride = 1u;
  if (_config.exportYieldMs == 0u) _config.exportYieldMs = 1u;
}

void PressureTraceRecorder::arm() {
  reset();
  _armed = true;
}

void PressureTraceRecorder::start(uint32_t tickMs) {
  if (!_armed) {
    return;
  }
  _capturing = true;
  _complete = false;
  _startTickMs = tickMs;
  _sampleStrideCounter = 0u;
  if (_eventCount < _config.maxEvents) {
    _events[_eventCount++] = PressureTraceEvent{
        0u, static_cast<uint8_t>(PressureTraceEventType::TraceStart), 0u, 0u, 0u};
  }
}

void PressureTraceRecorder::stop(uint32_t tickMs) {
  if (!_capturing) {
    return;
  }
  const uint32_t dt = tickMs - _startTickMs;
  if (_eventCount < _config.maxEvents) {
    _events[_eventCount++] = PressureTraceEvent{
        static_cast<uint16_t>((dt > 0xFFFFu) ? 0xFFFFu : dt),
        static_cast<uint8_t>(PressureTraceEventType::TraceStop),
        0u,
        0u,
        0u};
  }
  _capturing = false;
  _complete = true;
  _armed = false;
}

void PressureTraceRecorder::reset() {
  _sampleCount = 0;
  _eventCount = 0;
  _startTickMs = 0;
  _armed = false;
  _capturing = false;
  _complete = false;
  _sampleStrideCounter = 0u;
}

void PressureTraceRecorder::recordSample(PressureTraceChannel channel, const PressureTraceSample& sample) {
  if (!_capturing || !shouldRecordChannel(channel)) {
    return;
  }
  const uint16_t stride = (_config.sampleStride == 0u) ? 1u : _config.sampleStride;
  const bool shouldStore = (_sampleStrideCounter == 0u);
  _sampleStrideCounter = static_cast<uint16_t>((_sampleStrideCounter + 1u) % stride);
  if (!shouldStore || (_sampleCount >= _config.maxSamples)) {
    return;
  }
  _samples[_sampleCount++] = sample;
}

void PressureTraceRecorder::recordEvent(PressureTraceChannel channel, const PressureTraceEvent& event) {
  if (!_capturing || !shouldRecordChannel(channel) || (_eventCount >= _config.maxEvents)) {
    return;
  }
  _events[_eventCount++] = event;
}
