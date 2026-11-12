#!/bin/bash
# Видалити ShelfScan з Google Cloud після здачі.
REGION="${REGION:-europe-central2}"
SERVICE="${SERVICE:-shelfscan}"
gcloud run services delete "$SERVICE" --region "$REGION" --quiet
KEY_NAME=$(gcloud services api-keys list --filter="displayName=shelfscan-books" --format="value(name)" | head -n1)
[ -n "$KEY_NAME" ] && gcloud services api-keys delete "$KEY_NAME" --quiet
echo "Сервіс і API-ключ видалено. База Firestore лишилась (вона майже нічого не коштує);"
echo "щоб видалити і її: gcloud firestore databases delete --database='(default)'"
