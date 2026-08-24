if (typeof marked !== 'undefined') {
  marked.setOptions({
    gfm: true,
    breaks: false,
  });
}

function normalizeChatMarkdown(text) {
  let result = String(text || '').replace(/\r\n/g, '\n').trimEnd();
  result = result.replace(/^【([^】]+)】\s*$/gm, '### $1');
  result = result.replace(/^[ \t]{4}/gm, '');
  result = result.replace(/\n{3,}/g, '\n\n');
  const fenceCount = (result.match(/```/g) || []).length;
  if (fenceCount % 2 === 1) {
    result += '\n```';
  }
  return result;
}

function renderMarkdown(text) {
  if (!text) return '';

  const input = normalizeChatMarkdown(text);

  if (typeof marked === 'undefined') {
    return input
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  const html = marked.parse(input);

  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
  }

  return html;
}
