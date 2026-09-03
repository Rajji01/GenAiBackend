package com.ufc.backend.practice;
import java.io.*;
import java.util.*;

public class Solution {
    public static void main(String[] args) {
        int[][] matrix = {
                {1, 2, 3},
                {8, 9, 4},
                {7, 6, 5}
        };
        List<List<Integer>> ans=new Solution().pacificAtlantic(matrix);
        ans.forEach(i->{
            i.forEach(v->System.out.print(v+" "));
            System.out.println();
        });
    }
    int dir[][]={{-1,0},{1,0},{0,-1},{0,1}};

    public List<List<Integer>> pacificAtlantic(int[][] heights) {
        int pacific[][] = new int[heights.length][heights[0].length];
        int atlantic[][] = new int[heights.length][heights[0].length];

        int n = heights.length;
        int m = heights[0].length;
        for (int i = 0; i < m; i++) {
            pacific[0][i] = 1;
            atlantic[n - 1][i] = 1;
        }

        for (int i = 0; i < n; i++) {
            pacific[i][0] = 1;
            atlantic[i][m - 1] = 1;
        }


        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                if (pacific[i][j] != 1)
                    pacific[i][j] = bfs(i, j, heights, pacific, n, m) ? 1 : 0;
            }
        }
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                if (atlantic[i][j] != 1)
                    atlantic[i][j] = bfs(i, j, heights, atlantic, n, m) ? 1 : 0;
            }
        }
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                if (atlantic[i][j] != 1)
                    atlantic[i][j] = bfs(i, j, heights, atlantic, n, m) ? 1 : 0;
            }
        }
        List<List<Integer>> ans = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                if (atlantic[i][j] == 1 && pacific[i][j] == 1) {
                    ArrayList<Integer> arl = new ArrayList<>();
                    arl.add(i);
                    arl.add(j);
                    ans.add(arl);
                }
            }

        }
        return ans;
    }
        public boolean bfs( int i, int j, int ar[][], int flag[][], int n, int m){
            if(i<0||i>=n||j<0||j>=m) return false;
            if(flag[i][j]==1) return true;

            for(int c=0;c<dir.length;c++){
                int nx=i+dir[c][0];
                int ny=i+dir[c][1];

                if(nx>=0&&nx<n&&ny>=0&&ny<m&&ar[i][j]>=ar[nx][ny]&&bfs(nx,ny,ar,flag,n,m))
                {
                    flag[i][j]=1;
                    return true;
                };
            }
            return false;
        }
    }