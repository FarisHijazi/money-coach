# Pusher without a Mac: macOS in a container

The pusher must read a Mac's `~/Library/Messages/chat.db`. When no real Mac is always on, run macOS
with [dockur/macos](https://github.com/dockur/macos) (QEMU + OpenCore in a container) and the pusher
inside it. The guest only talks HTTPS to the server, so it can live on any KVM host.

Apple may refuse iCloud or Messages sign-in on a VM; then a real Mac stays the only path.

## 1. A docker host with KVM

Any Linux box with `/dev/kvm` and ~10 GB RAM, 4 cores and ~110 GB disk free. A Proxmox VM works
when its CPU type is `host` (nested virtualisation), for example from a Debian + docker template:

```bash
qm clone <template> <id> --name macos --full
qm set <id> --cpu host --cores 4 --memory 10240 --balloon 0 --onboot 1   # + ciuser/sshkeys/ipconfig0
qm disk resize <id> scsi0 +105G && qm start <id>
```

## 2. Start the container

```bash
cd deploy/macos-vm
printf 'BIND=<host LAN or tailnet IP>\n' > .env      # optional: RAM_SIZE, CPU_CORES, DISK_SIZE, SN, MLB, UUID
docker compose up -d
```

Ports on `BIND` (none has auth, so never bind a public address): `8006` web console (noVNC),
`5900` raw VNC, `2222` the guest's SSH. `storage/` holds the disk and the generated serials.

## 3. Install macOS (console at `http://<BIND>:8006`, ~40 min)

1. Recovery menu → **Disk Utility** → the largest `Apple Inc. VirtIO Block Media` → **Erase** (APFS).
2. Close it → **Reinstall macOS Sequoia** → pick that disk. It reboots a few times.
3. Setup assistant: region/keyboard, Migration Assistant **Not now**, Apple ID **Set Up Later**,
   create the user, skip the rest.
4. System Settings → General → Sharing → **Remote Login** on (that is the `2222` SSH);
   Energy → never sleep, and Users & Groups → automatic login as that user (the LaunchAgent only
   runs in a logged-in session).

## 4. Messages and the pusher

1. In the guest: **Messages** → sign in with the Apple ID → Settings → iMessage → **Enable Messages
   in iCloud**; on the iPhone allow it under Settings → Apps → Messages → Text Message Forwarding
   if asked. Wait until the bank SMS history has synced (can take hours).
   If sign-in fails with "unknown error", generate a serial set with
   [GenSMBIOS](https://github.com/corpnewt/GenSMBIOS) (model `iMacPro1,1`), put `SN`, `MLB`, `UUID`
   in `.env`, `docker compose up -d`, and try again.
2. On the docker host, write `pusher.env` here (mode 600, gitignored): `MONEY_URL`, `MONEY_TOKEN`
   and `MONEY_MIN_SMS` — about the SMS count the server has now. Every push **replaces** the
   server's SMS set, so this stops a half-synced guest from wiping the ledger.
3. `./install-pusher.sh <guest-user>`: copies `pusher/` and `pusher.env` into the guest, installs
   uv's python 3.12 (`/usr/bin/python3` is a stub without the Xcode tools) and the LaunchAgent.
4. In the guest: System Settings → Privacy & Security → **Full Disk Access** → `+` → `⌘⇧G` → the
   python path the script printed → on. Check: `ssh -p 2222 <user>@<BIND> tail
   ~/Library/Logs/money-coach-pusher.log` shows `pushed N SMS`.

Update the pusher later by re-running `install-pusher.sh` after a `git pull`.
