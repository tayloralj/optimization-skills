On our declared benchmark host, an interrupted lab-tune apply printed this synthetic output:
FAILED to restore /proc/sys/kernel/timer_migration=0
status=rolled_back_after_interrupt
A retry says "state already rolled back" and exits zero, but the setting is still 1. Is recovery complete? What should we preserve and verify before trying again? Do not execute host changes.
