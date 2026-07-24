# Remote dashboard access

Murmurent runs one dashboard per machine, bound to that machine's own
`127.0.0.1:8770`. A shared lab server therefore has its own dashboard,
separate from the one on your laptop. To view a server's dashboard from
your laptop, open an SSH tunnel to it. This page is the canonical
recipe: first-time setup on the server, the tunnel itself, the badge
that tells two dashboards apart, and a short troubleshooting list.

## The model in one sentence

Each machine's dashboard listens only on its own loopback interface.
Reaching it from anywhere else goes through an SSH tunnel, manual or
automatic, which is what keeps a dashboard safe to run on a machine you
are not sitting at.

## Step 1: first-time setup on the server

Do this once per server.

1. **Install Murmurent on the server.** It is the same one-line
   bootstrap used on any machine (see
   [Installing the CLI and commons](setup.md#installing-the-cli-and-commons-all-users)):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
   ```

2. **Set up SSH key access**, so future connections use your key
   instead of prompting for a password. From your laptop:

   ```bash
   ssh-keygen -t ed25519            # skip if you already have a key pair
   ssh-copy-id you@your-server
   ```

   `ssh-copy-id` copies your public key into the server's
   `~/.ssh/authorized_keys`. Confirm it worked with a plain
   `ssh you@your-server`: you should land on a shell prompt with no
   password.

3. **Start the dashboard on the server** and leave it running:

   ```bash
   murmurent dashboard --hifi
   ```

   For a server that should keep the dashboard up across reboots and
   logouts, run it as a systemd service instead; see the production
   deployment steps in
   [Setup: on the server, clone and install](setup.md#2-on-the-server-clone-and-install).

## Step 2: tunnel from your laptop

With the dashboard running on the server, pick one of three equivalent
routes.

### The shortcut command

```bash
murmurent dashboard --tunnel you@your-server
```

then open `http://localhost:8770` in your laptop's browser. `--tunnel`
accepts either a literal SSH destination, as above, or the name of a
host already registered with `murmurent host add`; in that case the
destination comes from `~/.murmurent/hosts.yaml`. See
[`ready_vs_projects.md`](ready_vs_projects.md) for registering a host.

### The manual recipe

```bash
ssh -N -L 8770:localhost:8770 you@your-server
```

then open `http://localhost:8770`. This is exactly what the shortcut
runs underneath; use it directly when you want to see the SSH command
or add your own SSH options. Ctrl+C stops the forward.

### Two dashboards side by side

Viewing two servers' dashboards from the same laptop at once needs two
different local ports. Add `--tunnel-port` to the second one:

```bash
murmurent dashboard --tunnel you@server-one                    # http://localhost:8770
murmurent dashboard --tunnel you@server-two --tunnel-port 8771 # http://localhost:8771
```

### VS Code Remote-SSH

If you already work on the server through VS Code's Remote-SSH
extension, running `murmurent dashboard --hifi` in its integrated
terminal is enough on its own: VS Code auto-forwards port 8770, and
the dashboard's own links resolve to the right machine. See
[The VSCode workflow](vscode-workflow.md) for the rest of the editor
layout.

## Telling dashboards apart: the identity badge

Every dashboard shows a small header badge naming the machine it
belongs to. With two tabs open side by side, your laptop's dashboard
and a tunnelled server's, the badge is how you tell which is which.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | The server does not have your public key yet | Run `ssh-copy-id you@your-server`, then retry |
| `bind: address already in use` on the laptop | Local port 8770 is already taken, often by another tunnel | Add `--tunnel-port 8771` and open `http://localhost:8771` instead |
| Browser shows "This site can't be reached" once the tunnel is up | Nothing is listening on the server's port 8770 yet | Start the dashboard on the server first with `murmurent dashboard --hifi`, then retry the tunnel |
| `ssh: connect to host ... port 22: Connection refused` | The server is unreachable, or `--tunnel` points at a host registry entry with the wrong `ssh_host` | Check `murmurent host list` and confirm the server is reachable |

## See also

- [Setup: on the server, clone and install](setup.md#2-on-the-server-clone-and-install) for running the dashboard as a systemd service.
- [The dashboard](dashboard.md) for what the dashboard shows once you are in.
- [`ready_vs_projects.md`](ready_vs_projects.md) for registering a server with `murmurent host add`.
- [CLI manual](cli_manual.md#dashboard) for the full `murmurent dashboard` flag reference.
