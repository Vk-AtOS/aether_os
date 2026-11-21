// Attachments travel inside the 64 KiB JSON body, so the cap is for the whole message.
export const MAX_ATT = 45 * 1024;

// The assistant's draft opens in the composer with its text, for the person to edit and send.
export const draftReply = (last, d) => ({
  id: last, draftId: d.id, to: (d.to || []).join(', '), subject: d.subject,
  text: d.text ?? d.body_text ?? d.body ?? '',
});
