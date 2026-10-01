Analytics implementation reference
==================================

RenderDox currently disables the inherited analytics subsystem with ``RENDERDOC_ANALYTICS_ENABLE=0``. Its load, prompt and report functions are inactive. This page describes the retained implementation for developers investigating that code.

The source is in `Analytics.h <https://github.com/dotm5/renderdox/blob/dgcore-main/qrenderdoc/Code/Interface/Analytics.h>`_ and the adjacent ``Analytics.cpp``. The current report request has an empty URL; there is no configured project collection endpoint.

The retained code defines monthly UI usage reports, an opt-in prompt and manual report review. Enabling a reporting service would require a separate implementation decision and endpoint configuration.

Retained report fields
----------------------

These fields describe the disabled implementation's report format.

Each report will contain metadata such as operating system version, RenderDoc version, which APIs have been used, which GPU vendor is in use (AMD, Intel, nVidia, etc) and whether a development or release build was run.

It may also include a handful of counters such as the average time taken to load a captured frame, and how many days in the month (as a number from 1-31) the program was used, to give a rough idea of how often people use RenderDoc.

Otherwise the majority of data is simple boolean flags. For each feature in the UI a flag is kept - these flags are left as false by default, and if the feature is ever used then the flag is set to true. There is nothing that stores how often the feature is used, or what it's used for.
