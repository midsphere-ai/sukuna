export type FileCategory = 'image' | 'pdf' | 'video' | 'audio' | 'code' | 'archive' | 'document';

export const extensionMap: Record<string, FileCategory> = {
	// Images
	jpg: 'image',
	jpeg: 'image',
	png: 'image',
	gif: 'image',
	webp: 'image',
	svg: 'image',
	bmp: 'image',
	ico: 'image',
	// PDF
	pdf: 'pdf',
	// Video
	mp4: 'video',
	webm: 'video',
	mov: 'video',
	avi: 'video',
	mkv: 'video',
	// Audio
	mp3: 'audio',
	wav: 'audio',
	ogg: 'audio',
	flac: 'audio',
	aac: 'audio',
	// Code
	js: 'code',
	ts: 'code',
	jsx: 'code',
	tsx: 'code',
	py: 'code',
	rb: 'code',
	go: 'code',
	rs: 'code',
	java: 'code',
	cpp: 'code',
	c: 'code',
	h: 'code',
	css: 'code',
	scss: 'code',
	html: 'code',
	json: 'code',
	yaml: 'code',
	yml: 'code',
	xml: 'code',
	sql: 'code',
	sh: 'code',
	// Archive
	zip: 'archive',
	tar: 'archive',
	gz: 'archive',
	rar: 'archive',
	'7z': 'archive',
	// Document
	doc: 'document',
	docx: 'document',
	txt: 'document',
	md: 'document',
	rtf: 'document',
	xls: 'document',
	xlsx: 'document',
	csv: 'document',
	ppt: 'document',
	pptx: 'document',
	log: 'document'
};

export function getFileCategory(filename: string): FileCategory {
	const ext = filename.split('.').pop()?.toLowerCase() || '';
	return extensionMap[ext] || 'document';
}
