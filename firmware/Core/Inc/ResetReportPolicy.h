#ifndef INC_RESETREPORTPOLICY_H_
#define INC_RESETREPORTPOLICY_H_

#include "CrashLog.h"

bool ResetReport_ShouldSend(const CrashLogSnapshot* snap);
bool ResetReport_ShouldAttemptDelivery(const CrashLogSnapshot* snap,
                                       bool hostReady,
                                       bool alreadySent);
bool ResetReport_ShouldIncludeRegulatorContext(const CrashLogSnapshot* snap);

#endif /* INC_RESETREPORTPOLICY_H_ */
