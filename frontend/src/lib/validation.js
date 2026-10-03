import { CHANNELS } from "./risk.js";

export const MAX_AMOUNT = 10_000_000_000;
export const MAX_ATTACHMENT_BYTES = 10 * 1024 ** 3;

export const EMPTY_FORM = {
  sender_name: "",
  sender_role: "",
  sender_known: false,
  sender_contact: "",
  channel: "",
  amount: "",
  beneficiary_name: "",
  beneficiary_is_new: false,
  message: "",
  attachment_name: "",
  attachment_size_kb: "",
  attachment_content_type: "",
};

/** Synthetic scenario from docs/DEMO_SCENARIO.md. */
export const DEMO_FORM = {
  sender_name: "Arvind Rao",
  sender_role: "Chief Executive Officer",
  sender_known: true,
  sender_contact: "+91 90000 12345",
  channel: "WhatsApp",
  amount: "18,50,000",
  beneficiary_name: "New Vendor X",
  beneficiary_is_new: true,
  message:
    "Urgent. I am in a board meeting and cannot take calls. Please release ₹18,50,000 to our new vendor today before 4 PM for a regulatory settlement. The RBI statement is attached. Keep this between us and confirm once it is done.",
  attachment_name: "RBI_Statement.zip",
  attachment_size_kb: "2457.6",
  attachment_content_type: "application/zip",
};

/** "18,50,000" / "₹ 1850000" -> 1850000, or null when not a whole positive number. */
export function parseAmount(text) {
  const digits = String(text).replace(/[,\s₹]/g, "");
  if (!/^\d+$/.test(digits)) return null;
  const value = Number(digits);
  return Number.isSafeInteger(value) ? value : null;
}

/** Returns { fieldName: message }. Empty object means the form is valid. Mirrors the backend rules. */
export function validateForm(form) {
  const errors = {};
  const len = (value) => value.trim().length;

  if (len(form.sender_name) < 2) errors.sender_name = "Enter the sender's name (at least 2 characters).";
  else if (len(form.sender_name) > 120) errors.sender_name = "Keep the name under 120 characters.";

  if (len(form.sender_role) < 2) errors.sender_role = "Enter the sender's role or title.";
  else if (len(form.sender_role) > 120) errors.sender_role = "Keep the role under 120 characters.";

  if (len(form.sender_contact) > 120) errors.sender_contact = "Keep this under 120 characters.";

  if (!CHANNELS.includes(form.channel)) errors.channel = "Select the channel the request arrived on.";

  const amount = parseAmount(form.amount);
  if (form.amount.trim() === "") errors.amount = "Enter the amount requested.";
  else if (amount === null) errors.amount = "Use whole rupees, digits only (commas are fine).";
  else if (amount <= 0) errors.amount = "Amount must be greater than zero.";
  else if (amount > MAX_AMOUNT) errors.amount = "Amount is above the supported maximum (₹1,000 crore).";

  if (len(form.beneficiary_name) < 2) errors.beneficiary_name = "Enter the beneficiary's name.";
  else if (len(form.beneficiary_name) > 160) errors.beneficiary_name = "Keep the name under 160 characters.";

  if (len(form.message) < 5) errors.message = "Paste the message text (at least 5 characters).";
  else if (len(form.message) > 5000) errors.message = "Keep the message under 5,000 characters.";

  const hasAttachmentName = len(form.attachment_name) > 0;
  const sizeText = form.attachment_size_kb.trim();
  const hasDetails = sizeText !== "" || len(form.attachment_content_type) > 0;
  if (hasDetails && !hasAttachmentName) errors.attachment_name = "Enter the file name to record attachment details.";
  if (len(form.attachment_name) > 255) errors.attachment_name = "Keep the file name under 255 characters.";
  if (len(form.attachment_content_type) > 120) errors.attachment_content_type = "Keep this under 120 characters.";
  if (sizeText !== "") {
    const kb = Number(sizeText);
    if (!Number.isFinite(kb) || kb < 0) errors.attachment_size_kb = "Enter the size in KB as a positive number.";
    else if (Math.round(kb * 1024) > MAX_ATTACHMENT_BYTES) errors.attachment_size_kb = "Size is above the supported maximum (10 GB).";
  }

  return errors;
}

/** Form state -> API payload (matches backend IncidentCreate). Call only after validateForm passes. */
export function toPayload(form) {
  const payload = {
    sender_name: form.sender_name.trim(),
    sender_role: form.sender_role.trim(),
    sender_known: form.sender_known,
    channel: form.channel,
    amount: parseAmount(form.amount),
    beneficiary_name: form.beneficiary_name.trim(),
    beneficiary_is_new: form.beneficiary_is_new,
    message: form.message.trim(),
  };
  if (form.sender_contact.trim()) payload.sender_contact = form.sender_contact.trim();
  if (form.attachment_name.trim()) {
    payload.attachment_name = form.attachment_name.trim();
    if (form.attachment_size_kb.trim() !== "") payload.attachment_size_bytes = Math.round(Number(form.attachment_size_kb) * 1024);
    if (form.attachment_content_type.trim()) payload.attachment_content_type = form.attachment_content_type.trim();
  }
  return payload;
}

/** Backend field names differ from form keys only for the attachment size. */
export function mapServerField(field) {
  return field === "attachment_size_bytes" ? "attachment_size_kb" : field;
}
