import { GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";

function getS3(): { client: S3Client; bucket: string } {
  const accountId = process.env.VIDEO_AI_R2_ACCOUNT_ID?.trim();
  const accessKeyId = process.env.VIDEO_AI_R2_ACCESS_KEY_ID?.trim();
  const secretAccessKey = process.env.VIDEO_AI_R2_SECRET_ACCESS_KEY?.trim();
  const endpoint =
    process.env.VIDEO_AI_R2_ENDPOINT?.trim() ||
    (accountId ? `https://${accountId}.r2.cloudflarestorage.com` : "");
  const bucket = process.env.VIDEO_AI_R2_BUCKET?.trim() ?? "";
  if (!endpoint || !accessKeyId || !secretAccessKey) {
    throw new Error("R2 is not configured (set VIDEO_AI_R2_ACCOUNT_ID, keys, and bucket)");
  }
  if (!bucket) throw new Error("VIDEO_AI_R2_BUCKET is not set");
  const client = new S3Client({
    region: "auto",
    endpoint,
    credentials: { accessKeyId, secretAccessKey },
  });
  return { client, bucket };
}

export async function r2GetText(key: string): Promise<string> {
  const { client, bucket } = getS3();
  const out = await client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  const body = out.Body;
  if (!body) throw new Error("Empty R2 object");
  return await body.transformToString();
}

export async function r2Put(key: string, data: Buffer, contentType: string): Promise<void> {
  const { client, bucket } = getS3();
  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: data,
      ContentType: contentType,
    }),
  );
}
