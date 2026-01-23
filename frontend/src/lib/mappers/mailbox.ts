export type MailMessageDTO = {
  id: number;
  mailbox: string;
  subject: string;
  from_email: string;
  to_emails: string;
  sent_at: string | null;
  attachments_count: number;
};

export type MailAttachmentDTO = {
  id: number;
  filename: string;
  content_type: string;
  size: number;
  file_url: string | null;
};

export type MailMessageDetailDTO = {
  id: number;
  mailbox: string;
  subject: string;
  from_email: string;
  to_emails: string;
  cc_emails: string;
  sent_at: string | null;
  body_text: string;
  body_html: string;
  attachments: MailAttachmentDTO[];
};

export type MailListDTO = {
  count: number;
  results: MailMessageDTO[];
};

export type MailMessage = {
  id: number;
  mailbox: string;
  subject: string;
  fromEmail: string;
  toEmails: string;
  sentAt: Date | null;
  attachmentsCount: number;
};

export type MailAttachment = {
  id: number;
  filename: string;
  contentType: string;
  size: number;
  fileUrl: string | null;
};

export type MailMessageDetail = {
  id: number;
  mailbox: string;
  subject: string;
  fromEmail: string;
  toEmails: string;
  ccEmails: string;
  sentAt: Date | null;
  bodyText: string;
  bodyHtml: string;
  attachments: MailAttachment[];
};

const toDate = (value: string | null): Date | null =>
  value ? new Date(value) : null;

export const mapMailMessage = (dto: MailMessageDTO): MailMessage => ({
  id: dto.id,
  mailbox: dto.mailbox,
  subject: dto.subject || "(bez predmeta)",
  fromEmail: dto.from_email,
  toEmails: dto.to_emails,
  sentAt: toDate(dto.sent_at),
  attachmentsCount: dto.attachments_count,
});

export const mapMailMessageDetail = (
  dto: MailMessageDetailDTO
): MailMessageDetail => ({
  id: dto.id,
  mailbox: dto.mailbox,
  subject: dto.subject || "(bez predmeta)",
  fromEmail: dto.from_email,
  toEmails: dto.to_emails,
  ccEmails: dto.cc_emails,
  sentAt: toDate(dto.sent_at),
  bodyText: dto.body_text,
  bodyHtml: dto.body_html,
  attachments: (dto.attachments || []).map((att) => ({
    id: att.id,
    filename: att.filename,
    contentType: att.content_type,
    size: att.size,
    fileUrl: att.file_url,
  })),
});

export const mapMailList = (dto: MailListDTO): { count: number; items: MailMessage[] } => ({
  count: dto.count,
  items: (dto.results || []).map(mapMailMessage),
});
