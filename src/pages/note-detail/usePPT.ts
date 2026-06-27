import { useState } from 'react';
import { uploadPPT, Slide } from '@/services/api';
import { getErrorMessage } from '@/lib/error';

export function usePPT(sessionId: string | undefined) {
  const [slides, setSlides] = useState<Slide[]>([]);
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);
  const [isUploadingPPT, setIsUploadingPPT] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);

  const handlePPTUpload = async (file: File) => {
    if (!file || !sessionId) return;
    setIsUploadingPPT(true);
    setUploadError(null);
    setUploadMessage(null);
    try {
      const result = await uploadPPT(file, sessionId);
      if (result.slides && result.slides.length > 0) {
        setSlides(result.slides);
        setActiveSlideIndex(0);
        setUploadMessage(`PPT 上传成功，共 ${result.slides.length} 页`);
      } else {
        setUploadMessage('PPT 上传成功，但没有解析到页面');
      }
    } catch (error: unknown) {
      console.error('PPT upload failed:', error);
      setUploadError(getErrorMessage(error) || 'PPT 上传失败，请确认文件格式后重试');
    }
    finally { setIsUploadingPPT(false); }
  };

  return {
    state: {
      slides,
      activeSlideIndex,
      isUploadingPPT,
      uploadError,
      uploadMessage,
    },
    actions: {
      setSlides,
      setActiveSlideIndex,
      setIsUploadingPPT,
      setUploadError,
      setUploadMessage,
      handlePPTUpload,
    },
  };
}
