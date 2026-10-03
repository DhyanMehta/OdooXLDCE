import { api } from "../services/api";

/** Open expense receipt in a new tab (credentials + blob URL for cross-origin API). */
export async function openExpenseReceipt(
  clubId: string,
  expenseId: string,
  attachmentId: string,
): Promise<void> {
  const url = api.receiptDownloadUrl(clubId, expenseId, attachmentId);
  const response = await fetch(url, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Could not download receipt (${response.status})`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  window.open(objectUrl, "_blank", "noopener,noreferrer");
}
