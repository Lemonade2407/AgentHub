/** 在浏览器把 DOCX 转成 HTML，用于简单的 Word 在线预览。 */
export async function loadDocxHtml(url: string): Promise<string> {
  const resp = await fetch(url)
  if (!resp.ok) {
    throw new Error(`文件加载失败（HTTP ${resp.status}）`)
  }
  const arrayBuffer = await resp.arrayBuffer()
  const mammoth = (await import('mammoth')).default
  const result = await mammoth.convertToHtml({ arrayBuffer })
  if (!result.value.trim()) {
    throw new Error('文档内容为空')
  }
  return result.value
}
