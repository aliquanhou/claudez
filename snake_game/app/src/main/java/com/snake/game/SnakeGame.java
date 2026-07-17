package com.snake.game;

import java.util.LinkedList;
import java.util.Random;

public class SnakeGame {
    public static final int GRID_SIZE = 20;
    public static final int TILE_COUNT = 16; // 16x16 网格

    public enum Direction { UP, DOWN, LEFT, RIGHT }

    private LinkedList<Point> snake;
    private Point food;
    private Direction direction;
    private Direction nextDirection;
    private boolean isRunning;
    private boolean gameOver;
    private int score;
    private Random random;

    public static class Point {
        public int x, y;
        public Point(int x, int y) {
            this.x = x;
            this.y = y;
        }
        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (o == null || getClass() != o.getClass()) return false;
            Point point = (Point) o;
            return x == point.x && y == point.y;
        }
    }

    public SnakeGame() {
        random = new Random();
        reset();
    }

    public void reset() {
        snake = new LinkedList<>();
        // 蛇初始位置在中间
        int startX = TILE_COUNT / 2;
        int startY = TILE_COUNT / 2;
        snake.addFirst(new Point(startX, startY));
        snake.addLast(new Point(startX - 1, startY));
        snake.addLast(new Point(startX - 2, startY));

        direction = Direction.RIGHT;
        nextDirection = Direction.RIGHT;
        isRunning = true;
        gameOver = false;
        score = 0;
        spawnFood();
    }

    public void setDirection(Direction dir) {
        // 防止180度掉头
        if ((dir == Direction.UP && direction != Direction.DOWN) ||
            (dir == Direction.DOWN && direction != Direction.UP) ||
            (dir == Direction.LEFT && direction != Direction.RIGHT) ||
            (dir == Direction.RIGHT && direction != Direction.LEFT)) {
            nextDirection = dir;
        }
    }

    public void update() {
        if (!isRunning || gameOver) return;

        direction = nextDirection;
        Point head = snake.getFirst();
        Point newHead = new Point(head.x, head.y);

        switch (direction) {
            case UP:    newHead.y--; break;
            case DOWN:  newHead.y++; break;
            case LEFT:  newHead.x--; break;
            case RIGHT: newHead.x++; break;
        }

        // 撞墙检测
        if (newHead.x < 0 || newHead.x >= TILE_COUNT ||
            newHead.y < 0 || newHead.y >= TILE_COUNT) {
            gameOver = true;
            isRunning = false;
            return;
        }

        // 撞自身检测
        for (Point p : snake) {
            if (p.equals(newHead)) {
                gameOver = true;
                isRunning = false;
                return;
            }
        }

        snake.addFirst(newHead);

        // 吃食物
        if (newHead.equals(food)) {
            score += 10;
            spawnFood();
        } else {
            snake.removeLast();
        }
    }

    private void spawnFood() {
        while (true) {
            int x = random.nextInt(TILE_COUNT);
            int y = random.nextInt(TILE_COUNT);
            Point p = new Point(x, y);
            if (!snake.contains(p)) {
                food = p;
                break;
            }
        }
    }

    // Getters
    public LinkedList<Point> getSnake() { return snake; }
    public Point getFood() { return food; }
    public int getScore() { return score; }
    public boolean isGameOver() { return gameOver; }
    public boolean isRunning() { return isRunning; }
}
