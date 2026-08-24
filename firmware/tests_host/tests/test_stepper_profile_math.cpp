#include "CppUTest/TestHarness.h"
#include "StepperProfileMath.h"

TEST_GROUP(StepperProfileMath)
{
};

TEST(StepperProfileMath, ArrForFreqGuardsZeroFrequency) {
    const uint32_t arr = StepperProfileMath::arrForFreq(1000u, 0u);
    UNSIGNED_LONGS_EQUAL(499u, arr);
}

TEST(StepperProfileMath, EaseFunctionsRespectEndpointsAndMonotonicity) {
    DOUBLES_EQUAL(0.0, StepperProfileMath::ease01(StepperProfileMath::Profile::SCurveCosine, 0.0f), 0.0001);
    DOUBLES_EQUAL(1.0, StepperProfileMath::ease01(StepperProfileMath::Profile::SCurveCosine, 1.0f), 0.0001);

    const float a = StepperProfileMath::ease01(StepperProfileMath::Profile::SCurveMinJerk, 0.25f);
    const float b = StepperProfileMath::ease01(StepperProfileMath::Profile::SCurveMinJerk, 0.75f);
    CHECK_TRUE(a > 0.0f);
    CHECK_TRUE(b > a);
    CHECK_TRUE(b < 1.0f);
}

TEST(StepperProfileMath, ShortMoveFallsBackToTriangularPlan) {
    StepperProfileMath::MovePlanInput input{};
    input.steps = 10u;
    input.requestedHz = 5000u;
    input.maxSpeedHz = 5000u;
    input.accelStepsPerSec2 = 1000.0f;
    input.timerClockHz = 1000000u;
    input.timerMaxArr = 0xFFFFu;

    const auto plan = StepperProfileMath::planMove(input);
    CHECK_TRUE(plan.triangular);
    CHECK_TRUE(plan.cruiseHz < 5000u);
    UNSIGNED_LONGS_EQUAL(plan.accelToggles, plan.decelToggles);
    CHECK_TRUE(plan.startArr >= plan.targetArr);
}

TEST(StepperProfileMath, TargetArrRespectsMinimumPulseWidth) {
    StepperProfileMath::MovePlanInput input{};
    input.steps = 200u;
    input.requestedHz = 200000u;
    input.maxSpeedHz = 200000u;
    input.accelStepsPerSec2 = 500000.0f;
    input.timerClockHz = 1000000u;
    input.timerMaxArr = 0xFFFFu;

    const auto plan = StepperProfileMath::planMove(input);
    CHECK_TRUE(plan.targetArr >= plan.minArr);
}

TEST(StepperProfileMath, ExplicitInitialRateProducesFreshResumePlan) {
    StepperProfileMath::MovePlanInput input{};
    input.steps = 10000u;
    input.requestedHz = 30000u;
    input.initialHz = 3000u;
    input.maxSpeedHz = 40000u;
    input.accelStepsPerSec2 = 140000.0f;
    input.timerClockHz = 1000000u;
    input.timerMaxArr = 0xFFFFFFFFu;

    const auto plan = StepperProfileMath::planMove(input);
    UNSIGNED_LONGS_EQUAL(3000u, plan.initialHz);
    UNSIGNED_LONGS_EQUAL(165u, plan.startArr);
    CHECK_TRUE(plan.startArr > plan.targetArr);
    UNSIGNED_LONGS_EQUAL(3183u, plan.accelSteps);
}

TEST(StepperProfileMath, LegacyInitialRateRemainsOneFifthOfCruise) {
    StepperProfileMath::MovePlanInput input{};
    input.steps = 10000u;
    input.requestedHz = 30000u;
    input.maxSpeedHz = 40000u;
    input.accelStepsPerSec2 = 140000.0f;
    input.timerClockHz = 1000000u;
    input.timerMaxArr = 0xFFFFFFFFu;

    const auto plan = StepperProfileMath::planMove(input);
    UNSIGNED_LONGS_EQUAL(0u, plan.initialHz);
    UNSIGNED_LONGS_EQUAL(plan.targetArr * 5u, plan.startArr);
}

TEST(StepperProfileMath, DirectZLogicalResumeMapsToExactThreeKilohertzArr) {
    StepperProfileMath::MovePlanInput input{};
    input.steps = 10000u;
    input.requestedHz = 15000u;
    input.initialHz = 1500u;
    input.maxSpeedHz = 15000u;
    input.accelStepsPerSec2 = 70000.0f;
    input.timerClockHz = 90000000u;
    input.timerMaxArr = 0xFFFFFFFFu;

    const auto plan = StepperProfileMath::planMove(input);
    UNSIGNED_LONGS_EQUAL(1500u, plan.initialHz);
    UNSIGNED_LONGS_EQUAL(29999u, plan.startArr);
    UNSIGNED_LONGS_EQUAL(1592u, plan.accelSteps);
}
