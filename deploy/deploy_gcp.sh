#!/bin/bash
# Розгортання ShelfScan у Google Cloud. Запускати з Cloud Shell у корені репозиторію:
#   PROJECT_ID=my-project bash deploy/deploy_gcp.sh
# Що робить:
#   1) вмикає потрібні API (Cloud Run, Cloud Build, Firestore, Books API, API Keys)
#   2) створює базу Firestore
#   3) дає сервісному акаунту Cloud Run доступ до Firestore
#   4) створює API-ключ, обмежений лише Google Books API
#   5) збирає контейнер з коду і запускає його в Cloud Run
set -e

PROJECT_ID="${PROJECT_ID:?Вкажи PROJECT_ID}"
REGION="${REGION:-europe-central2}"
SERVICE="${SERVICE:-shelfscan}"

gcloud config set project "$PROJECT_ID"

echo "== 1/5 Вмикаю API (1-2 хв)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com books.googleapis.com apikeys.googleapis.com

echo "== 2/5 Firestore..."
if ! gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  gcloud firestore databases create --location="$REGION" --type=firestore-native
else
  echo "База Firestore вже існує"
fi

echo "== 3/5 Права для сервісного акаунта..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
NEW_ROLES=0
for ROLE in roles/datastore.user roles/run.builder roles/serviceusage.serviceUsageConsumer \
            roles/cloudbuild.builds.builder roles/storage.objectViewer roles/artifactregistry.writer roles/logging.logWriter; do
  if ! gcloud projects get-iam-policy "$PROJECT_ID" --flatten="bindings[].members" \
       --filter="bindings.role=$ROLE AND bindings.members=serviceAccount:$SA" --format="value(bindings.role)" | grep -q .; then
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" \
      --role="$ROLE" --condition=None --quiet >/dev/null
    NEW_ROLES=1
  fi
done
if [ "$NEW_ROLES" = "1" ]; then
  echo "Нові права застосовуються в Google Cloud не одразу — чекаю 90 секунд..."
  sleep 90
fi

echo "== 4/5 API-ключ для Google Books..."
KEY_NAME=$(gcloud services api-keys list --filter="displayName=shelfscan-books" --format="value(name)" | head -n1)
if [ -z "$KEY_NAME" ]; then
  gcloud services api-keys create --display-name=shelfscan-books --api-target=service=books.googleapis.com
  KEY_NAME=$(gcloud services api-keys list --filter="displayName=shelfscan-books" --format="value(name)" | head -n1)
fi
BOOKS_API_KEY=$(gcloud services api-keys get-key-string "$KEY_NAME" --format="value(keyString)")

echo "== 5/5 Збираю і запускаю в Cloud Run (3-5 хв)..."
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --set-env-vars "BOOKS_API_KEY=$BOOKS_API_KEY" --memory 512Mi --max-instances 2 --quiet

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo
echo "Готово! ShelfScan працює тут: $URL"
echo "Відкрий це посилання на телефоні, щоб сканувати штрихкоди камерою."
