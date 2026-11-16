# Database backup and restore

The backup job makes a PostgreSQL custom-format dump, encrypts it with `age` or
GPG, sends the encrypted object and its SHA-256 manifest to a user-configured
`rclone` destination, and reads both objects back to verify them. It removes
only that run's local encrypted staging files after both remote objects have
been read back and verified. If an upload or verification fails, the encrypted
local files are retained. The SQL dump is streamed into the encryptor rather
than written as a plaintext file. This covers the PostgreSQL database only; it
does not back up application files, external wallet data, or Redis state.

The accompanying checksum is for corruption/transfer detection. It is not a
signature: protect the rclone account/configuration and independently protect
the encryption key. Do not treat successful upload as proof that a backup can
be decrypted or restored; perform controlled restore tests on a non-production
database.

## Host prerequisites and configuration

Install PostgreSQL client tools (`pg_dump` and `pg_restore`) compatible with
the server version, `rclone`, `sha256sum`, and exactly one of `age` or GPG.
Install the scripts and units from `deploy/` and `scripts/` at the paths used by
the units, which assume the application lives at `/opt/kola`. Create a dedicated
local staging directory owned by `kola`; do not point it at `/`, a
symlink, the application tree, or a shared temporary directory.

Create `/etc/kola/backup.env` with root ownership and permissions that
allow only root and the service account to read it. Do not commit this file.
Set the following values in the environment file; there are intentionally no
backup destination or key defaults:

```ini
BACKUP_LOCAL_DIR=/var/lib/kola-market/backup-staging
BACKUP_REMOTE=your-rclone-remote:your-chosen-path
BACKUP_ENCRYPTION=age
BACKUP_AGE_RECIPIENT=your-age-public-recipient
```

`BACKUP_LOCAL_DIR` must already exist and be writable by `kola`.
`BACKUP_REMOTE` must be a destination configured for the service's rclone
environment. Configure rclone using its protected config file and/or supported
environment variables; set `RCLONE_CONFIG` in this environment file if the
service must use a non-default config path. Do not put remote credentials in
the script or unit file.

For GPG instead, set `BACKUP_ENCRYPTION=gpg`,
`BACKUP_GPG_RECIPIENT=<your verified public-key recipient>`, and
`BACKUP_GPG_HOME=<the configured GPG keyring directory>` and omit the age
recipient. For age, restore additionally needs `BACKUP_AGE_IDENTITY` to name
the readable private identity file. For GPG restore, `BACKUP_GPG_HOME` must
contain the private decryption key. Keep private keys outside the repository
and restrict their access to the service account and root.

The `/opt/kola/.env` file used by the application must provide `POSTGRES_HOST`,
`POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_DB`, and `POSTGRES_PASSWORD` to the
backup service. Use the actual database credentials and do not copy example
values into production. Create and protect the local staging directory before
starting the unit.

## Enable and inspect backups

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now kola-backup.timer
systemctl list-timers kola-backup.timer
sudo systemctl start kola-backup.service
sudo journalctl -u kola-backup.service --since today
```

The timer is scheduled daily at 03:00 UTC and catches up after downtime.
Running the service manually performs a real backup; use it only after
configuring and reviewing the destination and encryption recipient. This
document does not execute backup or restore commands.

The service uses a unique UTC timestamp and refuses to overwrite an existing
remote object. On a failed transfer or remote read-back verification, review
the journal and retain the local encrypted staging files while investigating.
After a successful run the encrypted local copy is removed; retention,
immutability, and lifecycle policy for remote objects must be configured on
the chosen storage backend.

## Manual restore

Treat restore as a change-controlled operation. First select and independently
verify the intended remote backup and target database. Stop application
writers (web, worker, watcher, and scheduler units) and arrange a maintenance
window. Restore to a new, empty database where possible; the restore command
does not drop existing objects, but conflicting objects can make it fail.
Never use an unreviewed backup object or target.

Create `/etc/kola/restore.env`, root-owned and access-restricted, with
the exact selected remote paths and the target database repeated as the
confirmation value:

```ini
BACKUP_RESTORE_OBJECT=your-rclone-remote:your-chosen-path/kola-market-<timestamp>.dump.age
BACKUP_RESTORE_CHECKSUM_OBJECT=your-rclone-remote:your-chosen-path/kola-market-<timestamp>.dump.age.sha256
BACKUP_RESTORE_TARGET_DATABASE=your_explicit_restore_database
BACKUP_RESTORE_CONFIRM_DATABASE=your_explicit_restore_database
```

The extension must match `BACKUP_ENCRYPTION`. For age, configure
`BACKUP_AGE_IDENTITY` in the protected backup environment; for GPG, configure
`BACKUP_GPG_HOME`. The restore also uses the PostgreSQL host, port, user, and
password from `/opt/kola/.env`. The confirmation value must exactly match the
target database name or the script refuses to run.

Review the configured paths and target, then run the manual oneshot service:

```sh
sudo systemctl start kola-restore.service
sudo journalctl -u kola-restore.service --since today
```

The restore downloads the selected objects, verifies the encrypted file
against its manifest, decrypts only into the `pg_restore` pipeline, and uses a
single database transaction. A checksum mismatch, missing setting, decryption
failure, or PostgreSQL error fails the job. Verify the restored application
and data before restarting writers. Remove or disable the temporary
`restore.env` values after the operation.
