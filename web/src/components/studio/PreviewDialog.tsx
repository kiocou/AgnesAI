import { Download, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type PreviewDialogProps = {
  src: string;
  type: "image" | "video";
  title?: string;
  onOpenChange: (open: boolean) => void;
  onDownload?: () => void;
};

export function PreviewDialog({ src, type, title = "预览", onOpenChange, onDownload }: PreviewDialogProps) {
  return (
    <Dialog open={Boolean(src)} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[min(1120px,calc(100vw-2rem))] p-4">
        <DialogHeader className="pr-8">
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="media-checker flex max-h-[74vh] items-center justify-center overflow-hidden rounded-md border">
          {type === "video" ? (
            <video src={src} controls autoPlay className="max-h-[74vh] w-full bg-black object-contain" />
          ) : (
            <img src={src} alt={title} className="max-h-[74vh] w-full object-contain" />
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => window.open(src, "_blank", "noopener,noreferrer")}>
            <ExternalLink className="h-4 w-4" />
            打开
          </Button>
          {onDownload ? (
            <Button type="button" onClick={onDownload}>
              <Download className="h-4 w-4" />
              下载
            </Button>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
