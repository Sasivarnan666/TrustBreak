import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client.js";
import { Button, Card, PageHeader } from "../components/ui.jsx";
import { formatINR } from "../lib/format.js";
import { CHANNELS } from "../lib/risk.js";
import { DEMO_FORM, EMPTY_FORM, mapServerField, parseAmount, toPayload, validateForm } from "../lib/validation.js";

const INPUT =
  "mt-1.5 block w-full rounded-md border bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400";

function Field({ id, label, hint, error, optional, children }) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-800">
        {label}
        {optional && <span className="ml-1.5 text-xs font-normal text-slate-500">optional</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

function Check({ id, label, hint, checked, onChange }) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-start gap-3 rounded-md border border-slate-200 bg-slate-50/60 p-3">
      <input id={id} type="checkbox" checked={checked} onChange={onChange} className="mt-0.5 size-4 rounded border-slate-300" />
      <span>
        <span className="block text-sm font-medium text-slate-800">{label}</span>
        <span className="block text-xs text-slate-500">{hint}</span>
      </span>
    </label>
  );
}

export default function CreateIncident() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (name) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: undefined }));
  };

  const control = (name) => ({
    id: name,
    value: form[name],
    onChange: set(name),
    "aria-invalid": errors[name] ? "true" : undefined,
    "aria-describedby": errors[name] ? `${name}-error` : undefined,
    className: `${INPUT} ${errors[name] ? "border-red-400" : "border-slate-300"}`,
  });

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError(null);
    const found = validateForm(form);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setFormError("Fix the highlighted fields and try again.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.createIncident(toPayload(form));
      navigate(`/incidents/${response.data.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.details.length > 0) {
        const serverErrors = {};
        for (const detail of error.details) {
          if (detail.field && detail.field !== "_form") serverErrors[mapServerField(detail.field)] = detail.message;
        }
        setErrors(serverErrors);
        setFormError(error.message);
      } else {
        setFormError(error.message || "The incident could not be saved.");
      }
      setSubmitting(false);
    }
  }

  const amountPreview = parseAmount(form.amount);

  return (
    <>
      <PageHeader
        eyebrow="Cases"
        title="New incident"
        subtitle="Record a payment request exactly as it was received. Details are stored locally and marked for manual review."
        actions={
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setForm(DEMO_FORM);
              setErrors({});
              setFormError(null);
            }}
          >
            Load demo scenario
          </Button>
        }
      />

      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        {formError && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-800">
            {formError}
          </div>
        )}

        <Card title="1 · Sender">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field id="sender_name" label="Sender name" error={errors.sender_name}>
              <input {...control("sender_name")} type="text" autoComplete="off" placeholder="e.g. Arvind Rao" />
            </Field>
            <Field id="sender_role" label="Role / title" error={errors.sender_role}>
              <input {...control("sender_role")} type="text" autoComplete="off" placeholder="e.g. Chief Executive Officer" />
            </Field>
            <Field id="sender_contact" label="Phone / email / handle" optional error={errors.sender_contact} hint="As shown in the channel the request came from.">
              <input {...control("sender_contact")} type="text" autoComplete="off" />
            </Field>
            <div className="sm:pt-[1.6rem]">
              <Check
                id="sender_known"
                label="Known contact"
                hint="This person is in your organisation's records."
                checked={form.sender_known}
                onChange={set("sender_known")}
              />
            </div>
          </div>
        </Card>

        <Card title="2 · Channel & payment">
          <div className="grid gap-5 sm:grid-cols-2">
            <Field id="channel" label="Communication channel" error={errors.channel}>
              <select {...control("channel")}>
                <option value="">Select a channel</option>
                {CHANNELS.map((channel) => (
                  <option key={channel} value={channel}>
                    {channel}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              id="amount"
              label="Amount requested (₹)"
              error={errors.amount}
              hint={amountPreview ? `= ${formatINR(amountPreview)}` : "Whole rupees, e.g. 18,50,000"}
            >
              <input {...control("amount")} type="text" inputMode="numeric" autoComplete="off" placeholder="18,50,000" />
            </Field>
            <Field id="beneficiary_name" label="Beneficiary" error={errors.beneficiary_name}>
              <input {...control("beneficiary_name")} type="text" autoComplete="off" placeholder="Name on the payment instruction" />
            </Field>
            <div className="sm:pt-[1.6rem]">
              <Check
                id="beneficiary_is_new"
                label="New beneficiary"
                hint="Not previously paid by your organisation."
                checked={form.beneficiary_is_new}
                onChange={set("beneficiary_is_new")}
              />
            </div>
          </div>
        </Card>

        <Card title="3 · Message">
          <Field id="message" label="Message text" error={errors.message} hint={`${form.message.trim().length} / 5000 characters`}>
            <textarea {...control("message")} rows={6} placeholder="Paste the request exactly as received." />
          </Field>
        </Card>

        <Card title="4 · Attachment metadata">
          <p className="mb-4 text-sm text-slate-600">Optional. Record the file details only; nothing is uploaded.</p>
          <div className="grid gap-5 sm:grid-cols-3">
            <Field id="attachment_name" label="File name" optional error={errors.attachment_name}>
              <input {...control("attachment_name")} type="text" autoComplete="off" placeholder="RBI_Statement.zip" />
            </Field>
            <Field id="attachment_content_type" label="File type" optional error={errors.attachment_content_type}>
              <input {...control("attachment_content_type")} type="text" autoComplete="off" placeholder="application/zip" />
            </Field>
            <Field id="attachment_size_kb" label="Size (KB)" optional error={errors.attachment_size_kb}>
              <input {...control("attachment_size_kb")} type="text" inputMode="decimal" autoComplete="off" placeholder="2457.6" />
            </Field>
          </div>
        </Card>

        <div className="flex items-center justify-end gap-3">
          <Button type="button" variant="secondary" onClick={() => navigate("/incidents")} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Saving…" : "Submit incident"}
          </Button>
        </div>
      </form>
    </>
  );
}
