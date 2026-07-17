package com.snake.game;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

public class GameView extends SurfaceView implements SurfaceHolder.Callback, Runnable {
    private Thread gameThread;
    private volatile boolean running;
    private SnakeGame game;
    private Paint paint;
    private Paint textPaint;
    private Paint gridPaint;
    private float cellSize;
    private float offsetX, offsetY;
    private long lastUpdateTime;
    private static final long UPDATE_INTERVAL = 200; // 200ms 更新一次

    // 滑动检测
    private float touchStartX, touchStartY;
    private static final float SWIPE_THRESHOLD = 50;

    public GameView(Context context) {
        super(context);
        getHolder().addCallback(this);
        game = new SnakeGame();
        initPaints();
        setFocusable(true);
    }

    private void initPaints() {
        paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        textPaint.setColor(Color.WHITE);
        textPaint.setTextSize(40);
        textPaint.setTextAlign(Paint.Align.CENTER);
        gridPaint = new Paint();
        gridPaint.setColor(Color.parseColor("#2D2D44"));
        gridPaint.setStyle(Paint.Style.STROKE);
        gridPaint.setStrokeWidth(1);
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        running = true;
        gameThread = new Thread(this);
        gameThread.start();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
        // 计算网格大小，使游戏区域居中
        int size = Math.min(width, height) - 40;
        cellSize = (float) size / SnakeGame.TILE_COUNT;
        offsetX = (width - size) / 2f;
        offsetY = (height - size) / 2f;
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        running = false;
        try {
            gameThread.join();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void run() {
        lastUpdateTime = System.currentTimeMillis();
        while (running) {
            long now = System.currentTimeMillis();
            if (now - lastUpdateTime >= UPDATE_INTERVAL) {
                game.update();
                lastUpdateTime = now;
            }
            draw();
            // 控制帧率
            try {
                Thread.sleep(16); // ~60fps
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private void draw() {
        SurfaceHolder holder = getHolder();
        Canvas canvas = holder.lockCanvas();
        if (canvas == null) return;

        // 背景
        canvas.drawColor(Color.parseColor("#1A1A2E"));

        // 绘制网格
        float left = offsetX;
        float top = offsetY;
        float right = offsetX + SnakeGame.TILE_COUNT * cellSize;
        float bottom = offsetY + SnakeGame.TILE_COUNT * cellSize;

        for (int i = 0; i <= SnakeGame.TILE_COUNT; i++) {
            float x = left + i * cellSize;
            canvas.drawLine(x, top, x, bottom, gridPaint);
            float y = top + i * cellSize;
            canvas.drawLine(left, y, right, y, gridPaint);
        }

        // 绘制食物
        if (game.getFood() != null) {
            paint.setColor(Color.parseColor("#FF5722"));
            float fx = left + game.getFood().x * cellSize + 2;
            float fy = top + game.getFood().y * cellSize + 2;
            float fsize = cellSize - 4;
            canvas.drawRoundRect(new RectF(fx, fy, fx + fsize, fy + fsize), 8, 8, paint);
        }

        // 绘制蛇
        boolean first = true;
        for (SnakeGame.Point p : game.getSnake()) {
            if (first) {
                paint.setColor(Color.parseColor("#4CAF50")); // 蛇头
                first = false;
            } else {
                paint.setColor(Color.parseColor("#81C784")); // 蛇身
            }
            float sx = left + p.x * cellSize + 2;
            float sy = top + p.y * cellSize + 2;
            float ssize = cellSize - 4;
            canvas.drawRoundRect(new RectF(sx, sy, sx + ssize, sy + ssize), 6, 6, paint);
        }

        // 绘制分数
        canvas.drawText("分数: " + game.getScore(), getWidth() / 2f, 50, textPaint);

        // 游戏结束
        if (game.isGameOver()) {
            Paint overPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
            overPaint.setColor(Color.argb(180, 0, 0, 0));
            canvas.drawRect(0, 0, getWidth(), getHeight(), overPaint);

            Paint titlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
            titlePaint.setColor(Color.RED);
            titlePaint.setTextSize(80);
            titlePaint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText("游戏结束", getWidth() / 2f, getHeight() / 2f - 60, titlePaint);

            Paint scorePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
            scorePaint.setColor(Color.WHITE);
            scorePaint.setTextSize(50);
            scorePaint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText("最终得分: " + game.getScore(), getWidth() / 2f, getHeight() / 2f + 20, scorePaint);

            Paint tipPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
            tipPaint.setColor(Color.LTGRAY);
            tipPaint.setTextSize(35);
            tipPaint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText("点击屏幕重新开始", getWidth() / 2f, getHeight() / 2f + 90, tipPaint);
        }

        holder.unlockCanvasAndPost(canvas);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (game.isGameOver()) {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                game.reset();
            }
            return true;
        }

        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
                touchStartX = event.getX();
                touchStartY = event.getY();
                return true;
            case MotionEvent.ACTION_UP:
                float dx = event.getX() - touchStartX;
                float dy = event.getY() - touchStartY;
                if (Math.abs(dx) > SWIPE_THRESHOLD || Math.abs(dy) > SWIPE_THRESHOLD) {
                    if (Math.abs(dx) > Math.abs(dy)) {
                        game.setDirection(dx > 0 ? SnakeGame.Direction.RIGHT : SnakeGame.Direction.LEFT);
                    } else {
                        game.setDirection(dy > 0 ? SnakeGame.Direction.DOWN : SnakeGame.Direction.UP);
                    }
                }
                return true;
        }
        return super.onTouchEvent(event);
    }
}
