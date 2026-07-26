import base64
import os
import sys

import boto3

REGION = os.getenv("AWS_REGION", "us-east-2")
# us-east-2 não tem acesso "In-Region" a Nova Micro/Lite — só via Geo cross-region
# inference profile (destinos: us-east-1, us-east-2, us-west-2).
TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"
IMAGE_MODEL_ID = "us.amazon.nova-lite-v1:0"

# PNG 1x1 vermelho, só para validar o caminho multimodal — não é teste de OCR.
_TEST_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_text_model(client) -> None:
    response = client.converse(
        modelId=TEXT_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": "Responda em uma palavra: qual a capital do Brasil?"}],
            }
        ],
    )
    text = response["output"]["message"]["content"][0]["text"]
    print(f"[Nova Micro / texto] OK -> {text!r}")


def test_image_model(client) -> None:
    image_bytes = base64.b64decode(_TEST_IMAGE_B64)
    response = client.converse(
        modelId=IMAGE_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": image_bytes}}},
                    {"text": "Descreva o que você vê nesta imagem em uma frase curta."},
                ],
            }
        ],
    )
    text = response["output"]["message"]["content"][0]["text"]
    print(f"[Nova Lite / imagem] OK -> {text!r}")


def main() -> int:
    client = boto3.client("bedrock-runtime", region_name=REGION)
    try:
        test_text_model(client)
        test_image_model(client)
    except Exception as exc:
        print(f"FALHOU: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
