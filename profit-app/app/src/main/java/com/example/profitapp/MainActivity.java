package com.example.profitapp;

import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import java.text.DecimalFormat;

public class MainActivity extends AppCompatActivity {

    private EditText etCostPrice, etSellingPrice, etQuantity;
    private TextView tvRevenue, tvCost, tvProfit, tvProfitMargin, tvResultLabel;
    private Button btnCalculate, btnClear;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        etCostPrice = findViewById(R.id.et_cost_price);
        etSellingPrice = findViewById(R.id.et_selling_price);
        etQuantity = findViewById(R.id.et_quantity);
        tvRevenue = findViewById(R.id.tv_revenue);
        tvCost = findViewById(R.id.tv_cost);
        tvProfit = findViewById(R.id.tv_profit);
        tvProfitMargin = findViewById(R.id.tv_profit_margin);
        tvResultLabel = findViewById(R.id.tv_result_label);
        btnCalculate = findViewById(R.id.btn_calculate);
        btnClear = findViewById(R.id.btn_clear);

        btnCalculate.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                calculateProfit();
            }
        });

        btnClear.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                clearFields();
            }
        });
    }

    private void calculateProfit() {
        String costStr = etCostPrice.getText().toString().trim();
        String sellStr = etSellingPrice.getText().toString().trim();
        String qtyStr = etQuantity.getText().toString().trim();

        if (TextUtils.isEmpty(costStr) || TextUtils.isEmpty(sellStr) || TextUtils.isEmpty(qtyStr)) {
            Toast.makeText(this, "请填写所有字段", Toast.LENGTH_SHORT).show();
            return;
        }

        try {
            double costPrice = Double.parseDouble(costStr);
            double sellingPrice = Double.parseDouble(sellStr);
            int quantity = Integer.parseInt(qtyStr);

            if (costPrice <= 0 || sellingPrice <= 0 || quantity <= 0) {
                Toast.makeText(this, "请输入正数", Toast.LENGTH_SHORT).show();
                return;
            }

            double totalRevenue = sellingPrice * quantity;
            double totalCost = costPrice * quantity;
            double profit = totalRevenue - totalCost;
            double profitMargin = (profit / totalRevenue) * 100;

            DecimalFormat df = new DecimalFormat("#,##0.00");

            tvRevenue.setText("¥" + df.format(totalRevenue));
            tvCost.setText("¥" + df.format(totalCost));

            if (profit >= 0) {
                tvProfit.setTextColor(getResources().getColor(R.color.green));
                tvProfit.setText("+¥" + df.format(profit));
                tvProfitMargin.setTextColor(getResources().getColor(R.color.green));
                tvResultLabel.setText("✅ 盈利！");
                tvResultLabel.setTextColor(getResources().getColor(R.color.green));
            } else {
                tvProfit.setTextColor(getResources().getColor(R.color.red));
                tvProfit.setText("-¥" + df.format(Math.abs(profit)));
                tvProfitMargin.setTextColor(getResources().getColor(R.color.red));
                tvResultLabel.setText("❌ 亏损");
                tvResultLabel.setTextColor(getResources().getColor(R.color.red));
            }

            tvProfitMargin.setText(df.format(profitMargin) + "%");

        } catch (NumberFormatException e) {
            Toast.makeText(this, "请输入有效的数字", Toast.LENGTH_SHORT).show();
        }
    }

    private void clearFields() {
        etCostPrice.setText("");
        etSellingPrice.setText("");
        etQuantity.setText("");
        tvRevenue.setText("¥0.00");
        tvCost.setText("¥0.00");
        tvProfit.setText("¥0.00");
        tvProfitMargin.setText("0.00%");
        tvResultLabel.setText("等待计算...");
        tvResultLabel.setTextColor(getResources().getColor(R.color.gray));
        tvProfit.setTextColor(getResources().getColor(R.color.black));
        tvProfitMargin.setTextColor(getResources().getColor(R.color.black));
    }
}
