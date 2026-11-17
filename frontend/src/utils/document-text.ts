/** 文件选择框可接受的后缀（.doc 旧格式不支持） */
export const DOCUMENT_ACCEPT = '.txt,.md,.pdf,.docx'

/**
 * 在浏览器本地提取文档文字，不上传文件。
 * 解析库按需动态加载，避免拖慢 Agent 编辑器首屏。
 */
export async function extractDocumentText(file: File): Promise<string> {
  const name = file.name.toLowerCase()
  if (name.endsWith('.txt') || name.endsWith('.md')) {
    return file.text()
  }
  if (name.endsWith('.pdf')) {
    return extractPdf(file)
  }
  if (name.endsWith('.docx')) {
    return extractDocx(file)
  }
  throw new Error('仅支持 txt / md / pdf / docx 文件')
}

async function extractPdf(file: File): Promise<string> {
  const pdfjsLib = await import('pdfjs-dist')
  const { default: pdfWorker } = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

  const data = new Uint8Array(await file.arrayBuffer())
  const loadingTask = pdfjsLib.getDocument({ data })
  const document = await loadingTask.promise
  try {
    const pages: string[] = []
    for (let index = 1; index <= document.numPages; index += 1) {
      const page = await document.getPage(index)
      const content = await page.getTextContent()
      const text = content.items
        .map((item) => ('str' in item ? item.str : ''))
        .join(' ')
        .trim()
      if (text) pages.push(text)
    }
    return pages.join('\n\n')
  } finally {
    await loadingTask.destroy()
  }
}

async function extractDocx(file: File): Promise<string> {
  const mammoth = (await import('mammoth')).default
  const arrayBuffer = await file.arrayBuffer()
  const result = await mammoth.extractRawText({ arrayBuffer })
  return result.value
}
