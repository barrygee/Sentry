# nmcli output fixtures

Sample `nmcli --terse --colors no` output for the pure parsers in
`app/backend/adapters/nmcli_wifi_ap.py`. Keeping them as files rather than
inline strings means the escaping is preserved exactly as `nmcli` writes it —
which is the whole point, since terse-mode escaping (`\:` for a literal colon,
`\\` for a literal backslash) is the part that silently corrupts a naive
`split(":")`.

Every fixture is captured with `LC_ALL=C`, matching how the adapter invokes
`nmcli`. Field labels are localised without it, and every parser here matches
them by name.

| File | Command it came from |
|---|---|
| `device_status.txt` | `nmcli --terse --colors no -f DEVICE,TYPE,STATE,CONNECTION device status` |
| `device_status_colon_ssid.txt` | The same, where the joined network's name contains a literal `:` |
| `device_show_wlan0.txt` | `nmcli --terse --colors no -f GENERAL.STATE,GENERAL.HWADDR,... device show wlan0` |
| `device_show_wlan1_idle.txt` | The same for an idle second radio — no addresses, no gateway |
| `connection_show_hotspot.txt` | `nmcli --terse --colors no -f connection.id,... connection show sentry-hotspot` |
| `connection_show_active.txt` | `nmcli --terse --colors no -f NAME,DEVICE connection show --active` |

None of these contain a passphrase, and none ever should: the adapter never
invokes `nmcli` with `-s`/`--show-secrets`, so a real capture cannot contain one
either.
