# Resume Bundle

- run_name: `vinbig_v3_competition_yolo11m_832`
- source_run_dir: `/kaggle/working/runs/vinbig_v3_competition_yolo11m_832`
- resume_weight: `weights/last.pt`
- inference_weight: `weights/best.pt`
- train_config: `configs/experiments/version3_competition.yaml`
- dataset_root: `/kaggle/input/<ten-dataset>/dataset_yolo_balanced`

Lenh train tiep V3 tren Kaggle:

python kaggle_run_balanced.py \
  --train-config configs/experiments/version3_competition.yaml \
  --model /kaggle/input/<resume-dataset>/resume_bundle_vinbig_v3_competition_yolo11m_832_20260320_233355/weights/last.pt \
  --dataset-root /kaggle/input/<ten-dataset>/dataset_yolo_balanced \
  --name vinbig_v3_competition_yolo11m_832_resume \
  --epochs 20 \
  --export-resume-bundle \
  --zip-artifacts

Ghi chu:
- `last.pt`: train tiep
- `best.pt`: predict/evaluate