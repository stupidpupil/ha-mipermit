# MiPermit Integration for Home Assistant

This is a custom integration for Home Assistant that adds service actions to query and activate visitor parking permits using [MiPermit](https://mipermit.com/).


> [!CAUTION]
> This project includes code produced with a "generative AI". This is documented here for transparency.


## Requirements

This integration needs a 'headless' browser that understands the Chrome DevTools Protocol (CDP) over a websocket.

The easiest way to set this up is probably [alexbelgium's _Browserless Chrome_ Home Assistant add-on](https://github.com/alexbelgium/hassio-addons/tree/master/browserless_chrome), and this integration assumes that you're using this by default.


## License

This project uses the MIT license.

> [!WARNING]
> This project is entirely unaffiliated with MiPermit Ltd, and any of MiPermit's partners, suppliers or customers.

## Installation

> [!CAUTION]
> This integration is offered **without any warranty**. 
> It may break at any time and you will be liable for any consequences.
> I will **not** be paying your parking tickets.


[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stupidpupil&repository=ha-mipermit&category=integration)

> [!TIP]
> You can create a unique 'member login' for Home Assistant to login into MiPermit in the [_Members & Vehicles_](https://secure.mipermit.com/root/Account/MemberManagement.aspx) section of the MiPermit website.



## Example action calls and responses

### `mipermit.get_permits`

Retrieves all currently **active** visitor permits for a given operator.

| Parameter  | Type   | Required | Description                                          |
|------------|--------|----------|------------------------------------------------------|
| `operator` | string | Yes      | Car Park Operator name (e.g. `Cardiff City Council`) |


```yaml
action: mipermit.get_permits
data:
  operator: "Cardiff City Council"
```

```yaml
success: true

permits:
  - registration: BD51SMR
    valid: 01/06/2026 15:22 to 16:22
    remaining_time: 1 hour
    status: Active # Only Active permits are returned
```

---

### `mipermit.activate_permit`

Activates a new visitor permit.

| Parameter      | Type    | Required | Description                                                           |
|----------------|---------|----------|-----------------------------------------------------------------------|
| `operator`     | string  | Yes      | Car Park Operator name (e.g. `Cardiff City Council`)                  |
| `registration` | string  | Yes      | Vehicle registration number (e.g. `BD51SMR`)                         |
| `permit_type`  | string  | Yes      | Case-sensitive regex matched against permit type options (e.g. `Red`) |
| `duration`     | integer | Yes      | Duration in whole hours, 1–100 (e.g. `1`)                            |


```yaml
action: mipermit.activate_permit
data:
  operator: "Cardiff City Council"
  registration: "BD51SMR"
  permit_type: "Red"
  duration: 1
```

```yaml
success: true

permit:
  registration: BD51SMR
  valid: 01/06/2026 15:23 to 16:23
  remaining_time: 1 hour
  status: Active

all_active_permits:
  - registration: BD51SMR
    valid: 01/06/2026 15:23 to 16:23
    remaining_time: 1 hour
    status: Active

```


## Notes

- Each action opens a fresh browser context in the remote Browserless instance,
  logs in to MiPermit, and navigates the site. Expect each call to take 10–30
  seconds depending on network conditions.

- The `permit_type` parameter is a **case-sensitive regular expression**, so
  `Red` matches `"(762 available) - Visitor - Red (850 x 1 hour) - 1 hour"`.
  Use `(?i)red` for case-insensitive matching.

