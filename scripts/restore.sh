#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() {
    printf 'kola-restore: ERROR: %s\n' "$*" >&2
    exit 1
}

for command_name in mktemp rm sha256sum awk rclone pg_restore; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command is missing: $command_name"
done

: "${BACKUP_LOCAL_DIR:?Set BACKUP_LOCAL_DIR to a pre-created writable directory.}"
: "${BACKUP_ENCRYPTION:?Set BACKUP_ENCRYPTION to age or gpg.}"
: "${BACKUP_RESTORE_OBJECT:?Set BACKUP_RESTORE_OBJECT to the exact encrypted rclone object path.}"
: "${BACKUP_RESTORE_CHECKSUM_OBJECT:?Set BACKUP_RESTORE_CHECKSUM_OBJECT to the matching checksum object path.}"
: "${BACKUP_RESTORE_TARGET_DATABASE:?Set BACKUP_RESTORE_TARGET_DATABASE to the explicit restore database.}"
: "${BACKUP_RESTORE_CONFIRM_DATABASE:?Set BACKUP_RESTORE_CONFIRM_DATABASE to the exact target database name to authorize restore.}"
: "${POSTGRES_HOST:?Set POSTGRES_HOST.}"
: "${POSTGRES_PORT:?Set POSTGRES_PORT.}"
: "${POSTGRES_USER:?Set POSTGRES_USER.}"
: "${POSTGRES_DB:?Set POSTGRES_DB.}"
: "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD.}"

[[ "$BACKUP_LOCAL_DIR" == /* ]] || die "BACKUP_LOCAL_DIR must be an absolute path."
[[ -d "$BACKUP_LOCAL_DIR" && ! -L "$BACKUP_LOCAL_DIR" ]] || die "BACKUP_LOCAL_DIR must already exist and must not be a symlink."
[[ "$POSTGRES_PORT" =~ ^[0-9]+$ ]] || die "POSTGRES_PORT must be numeric."
[[ "$BACKUP_RESTORE_TARGET_DATABASE" == "$BACKUP_RESTORE_CONFIRM_DATABASE" ]] || die "restore confirmation does not exactly match the target database; refusing to restore."
[[ "$BACKUP_RESTORE_TARGET_DATABASE" != "$POSTGRES_DB" ]] || die "refusing to restore over the configured application database."

case "$BACKUP_ENCRYPTION" in
    age)
        : "${BACKUP_AGE_IDENTITY:?Set BACKUP_AGE_IDENTITY to a readable private identity file when BACKUP_ENCRYPTION=age.}"
        [[ -r "$BACKUP_AGE_IDENTITY" ]] || die "BACKUP_AGE_IDENTITY is not readable."
        command -v age >/dev/null 2>&1 || die "required command is missing: age"
        extension=age
        ;;
    gpg)
        : "${BACKUP_GPG_HOME:?Set BACKUP_GPG_HOME to the GPG home containing the private decryption key.}"
        [[ -d "$BACKUP_GPG_HOME" && ! -L "$BACKUP_GPG_HOME" ]] || die "BACKUP_GPG_HOME must be an existing directory and must not be a symlink."
        command -v gpg >/dev/null 2>&1 || die "required command is missing: gpg"
        export GNUPGHOME="$BACKUP_GPG_HOME"
        extension=gpg
        ;;
    *)
        die "BACKUP_ENCRYPTION must be either age or gpg."
        ;;
esac

filename="${BACKUP_RESTORE_OBJECT##*/}"
[[ "$filename" == *.dump."$extension" ]] || die "restore object extension does not match BACKUP_ENCRYPTION."

encrypted_tmp=""
checksum_tmp=""
cleanup() {
    [[ -z "$encrypted_tmp" ]] || rm -f -- "$encrypted_tmp"
    [[ -z "$checksum_tmp" ]] || rm -f -- "$checksum_tmp"
}
trap cleanup EXIT

encrypted_tmp="$(mktemp "${BACKUP_LOCAL_DIR}/.kola-restore.XXXXXX")"
checksum_tmp="$(mktemp "${BACKUP_LOCAL_DIR}/.kola-restore-checksum.XXXXXX")"

printf 'kola-restore: downloading the explicitly configured encrypted object and checksum.\n'
rclone copyto "$BACKUP_RESTORE_OBJECT" "$encrypted_tmp"
rclone copyto "$BACKUP_RESTORE_CHECKSUM_OBJECT" "$checksum_tmp"

read -r expected_digest manifest_filename extra < "$checksum_tmp" || die "checksum manifest is empty."
[[ -z "${extra:-}" ]] || die "checksum manifest has unexpected fields."
[[ "$expected_digest" =~ ^[0-9a-f]{64}$ ]] || die "checksum manifest has an invalid SHA-256 digest."
[[ "$manifest_filename" == "$filename" ]] || die "checksum manifest filename does not match the selected backup."
actual_digest="$(sha256sum -- "$encrypted_tmp" | awk '{print $1}')"
[[ "$actual_digest" == "$expected_digest" ]] || die "downloaded backup checksum verification failed; refusing to restore."

export PGPASSWORD="$POSTGRES_PASSWORD"
printf 'kola-restore: checksum verified; restoring into the explicitly confirmed target database.\n'

case "$BACKUP_ENCRYPTION" in
    age)
        age --decrypt --identity "$BACKUP_AGE_IDENTITY" "$encrypted_tmp" |
            pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
                --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
                --username="$POSTGRES_USER" --dbname="$BACKUP_RESTORE_TARGET_DATABASE"
        ;;
    gpg)
        gpg --batch --decrypt "$encrypted_tmp" |
            pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
                --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
                --username="$POSTGRES_USER" --dbname="$BACKUP_RESTORE_TARGET_DATABASE"
        ;;
esac

printf 'kola-restore: restore completed successfully.\n'
