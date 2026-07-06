import { useRef, useState, type ReactNode } from "react";
import { ImagePlus, UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn, fileToDataUri } from "@/lib/utils";

export type ReferenceImage = {
  value: string;
  src: string;
  label: string;
};

type UploadDropzoneProps = {
  title: string;
  description: string;
  images: ReferenceImage[];
  multiple?: boolean;
  onChange: (images: ReferenceImage[]) => void;
  onError: (message: string) => void;
  actions?: ReactNode;
};

export function UploadDropzone({
  title,
  description,
  images,
  multiple = true,
  onChange,
  onError,
  actions,
}: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  async function addFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
    if (!files.length) return;
    setBusy(true);
    try {
      const next: ReferenceImage[] = multiple ? [...images] : [];
      for (const file of files) {
        const value = await fileToDataUri(file);
        if (value) next.push({ value, src: URL.createObjectURL(file), label: file.name });
        if (!multiple) break;
      }
      onChange(next);
    } catch (error) {
      onError(error instanceof Error ? error.message : "上传失败");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        className={cn(
          "upload-dropzone group flex min-h-[132px] w-full flex-col items-center justify-center rounded-lg border border-dashed bg-muted/35 px-4 py-5 text-center hover:border-primary hover:bg-primary/5",
          dragging && "border-primary bg-primary/10",
        )}
        data-dragging={dragging}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void addFiles(event.dataTransfer.files);
        }}
      >
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept="image/*"
          multiple={multiple}
          onChange={(event) => {
            if (event.target.files) void addFiles(event.target.files);
          }}
        />
        <div className="upload-icon mb-3 rounded-md border bg-background p-2 shadow-sm">
          {busy ? <UploadCloud className="h-5 w-5 animate-pulse text-primary" /> : <ImagePlus className="h-5 w-5 text-primary" />}
        </div>
        <div className="text-sm font-semibold">{title}</div>
        <div className="mt-1 max-w-[260px] text-xs leading-5 text-muted-foreground">{description}</div>
      </button>

      {images.length ? (
        <div className="flex flex-wrap gap-2">
          {images.map((image, index) => (
            <div key={`${image.label}-${index}`} className="motion-thumb group relative h-16 w-16 overflow-hidden rounded-md border bg-muted">
              <img src={image.src || image.value} alt={image.label} className="h-full w-full object-cover" />
              <button
                type="button"
                className="absolute right-1 top-1 rounded-full bg-studio-ink/75 p-1 text-white opacity-0 transition group-hover:opacity-100"
                onClick={() => onChange(images.filter((_, itemIndex) => itemIndex !== index))}
              >
                <X className="h-3 w-3" />
                <span className="sr-only">移除</span>
              </button>
            </div>
          ))}
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange([])}>
            清空
          </Button>
        </div>
      ) : null}

      {actions}
    </div>
  );
}
