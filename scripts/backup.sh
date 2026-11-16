#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() {
    printf 'kola-backup: ERROR: %s\n' "$*" >&2
    exit 1
}

for command_name in date mktemp mv rm sha256sum awk rclone pg_dump; do
    command -v "$command_name" >/dev/null 2>&1 || die "required command is missing: $command_name"
done

: "${BACKUP_LOCAL_DIR:?Set BACKUP_LOCAL_DIR to a pre-created writable directory.}"
: "${BACKUP_REMOTE:?Set BACKUP_REMOTE to the configured rclone remote and destination path.}"
: "${BACKUP_ENCRYPTION:?Set BACKUP_ENCRYPTION to age or gpg.}"
: "${POSTGRES_HOST:?Set POSTGRES_HOST.}"
: "${POSTGRES_PORT:?Set POSTGRES_PORT.}"
: "${POSTGRES_USER:?Set POSTGRES_USER.}"
: "${POSTGRES_DB:?Set POSTGRES_DB.}"
: "${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD.}"

[[ "$BACKUP_LOCAL_DIR" == /* ]] || die "BACKUP_LOCAL_DIR must be an absolute path."
[[ -d "$BACKUP_LOCAL_DIR" && ! -L "$BACKUP_LOCAL_DIR" ]] || die "BACKUP_LOCAL_DIR must already exist and must not be a symlink."
[[ -n "${BACKUP_REMOTE//[[:space:]]/}" ]] || die "BACKUP_REMOTE must not be empty or whitespace."
[[ "$POSTGRES_PORT" =~ ^[0-9]+$ ]] || die "POSTGRES_PORT must be numeric."

case "$BACKUP_ENCRYPTION" in
    age)
        : "${BACKUP_AGE_RECIPIENT:?Set BACKUP_AGE_RECIPIENT when BACKUP_ENCRYPTION=age.}"
        command -v age >/dev/null 2>&1 || die "required command is missing: age"
        extension=age
        ;;
    gpg)
        : "${BACKUP_GPG_RECIPIENT:?Set BACKUP_GPG_RECIPIENT when BACKUP_ENCRYPTION=gpg.}"
        : "${BACKUP_GPG_HOME:?Set BACKUP_GPG_HOME to the GPG home containing the public encryption key.}"
        [[ -d "$BACKUP_GPG_HOME" && ! -L "$BACKUP_GPG_HOME" ]] || die "BACKUP_GPG_HOME must be an existing directory and must not be a symlink."
        command -v gpg >/dev/null 2>&1 || die "required command is missing: gpg"
        export GNUPGHOME="$BACKUP_GPG_HOME"
        extension=gpg
        ;;
    *)
        die "BACKUP_ENCRYPTION must be either age or gpg."
        ;;
esac

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
filename="kola-market-${stamp}.dump.${extension}"
archive="${BACKUP_LOCAL_DIR}/${filename}"
checksum_file="${archive}.sha256"
partial=""

[[ ! -e "$archive" && ! -e "$checksum_file" ]] || die "backup name already exists; refusing to overwrite it."

cleanup() {
    if [[ -n "$partial" ]]; then
        rm -f -- "$partial"
    fi
}
trap cleanup EXIT

partial="$(mktemp "${BACKUP_LOCAL_DIR}/.kola-market-${stamp}.XXXXXX.partial")"
export PGPASSWORD="$POSTGRES_PASSWORD"

case "$BACKUP_ENCRYPTION" in
    age)
        pg_dump --format=custom --no-owner --no-acl \
            --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
            --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" |
            age --recipient "$BACKUP_AGE_RECIPIENT" > "$partial"
        ;;
    gpg)
        pg_dump --format=custom --no-owner --no-acl \
            --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
            --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" |
            gpg --batch --encrypt --recipient "$BACKUP_GPG_RECIPIENT" > "$partial"
        ;;
esac

[[ -s "$partial" ]] || die "encryption produced an empty backup."
mv -- "$partial" "$archive"
partial=""

digest="$(sha256sum -- "$archive" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$filename" > "$checksum_file"

remote_base="${BACKUP_REMOTE%/}"
remote_archive="${remote_base}/${filename}"
remote_checksum="${remote_archive}.sha256"

printf 'kola-backup: uploading encrypted backup to configured rclone destination.\n'
rclone copyto --immutable "$archive" "$remote_archive"
rclone copyto --immutable "$checksum_file" "$remote_checksum"

remote_digest="$(rclone cat "$remote_archive" | sha256sum | awk '{print $1}')"
[[ "$remote_digest" == "$digest" ]] || die "remote backup checksum verification failed; local encrypted files were retained."

remote_manifest="$(rclone cat "$remote_checksum")"
local_manifest="$(< "$checksum_file")"
[[ "$remote_manifest" == "$local_manifest" ]] || die "remote checksum manifest verification failed; local encrypted files were retained."

# Remove only this run's encrypted local copy after remote read-back verification.
rm -- "$archive" "$checksum_file"
printf 'kola-backup: remote upload and verification succeeded; local encrypted staging files removed.\n'
