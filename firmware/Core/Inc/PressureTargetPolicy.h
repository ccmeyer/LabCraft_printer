#ifndef INC_PRESSURETARGETPOLICY_H_
#define INC_PRESSURETARGETPOLICY_H_

namespace PressureTargetPolicy {

// Target changes should only wait for a ready bit when the regulator loop is
// active. If regulation is paused, the target is updated for later use and the
// command should complete immediately.
constexpr bool shouldWaitForReadyAfterTargetChange(bool regulatorActive)
{
  return regulatorActive;
}

}  // namespace PressureTargetPolicy

#endif /* INC_PRESSURETARGETPOLICY_H_ */
