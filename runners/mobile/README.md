# TestMona Mobile Runner

This worker connects to an existing Appium 2 endpoint and an Android or iOS
device supplied by that environment. It does not bundle an emulator, Xcode, or
a device into TestMona. Configure `appium_url` on the selected execution
environment or set `APPIUM_URL`, register a `mobile` Runner, then start:

```sh
docker compose --profile mobile-runner up --build mobile-runner
```

If Appium is offline or no requested device can create a session, the task is
reported as `blocked`. Supported fixed actions are tap, type, swipe, screenshot,
text assertion, and visibility assertion. iOS still requires a macOS/Xcode host
behind Appium.
