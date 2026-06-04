package handler

import (
	"net/http"
	"slices"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/model"
)

// GetModels 返回数据库中可用的模型列表。
func (h *Handler) GetModels(c *gin.Context) {
	modelSet := map[string]struct{}{}

	var fromSubmission []string
	h.DB.Model(&model.Submission{}).Distinct("model_name").Pluck("model_name", &fromSubmission)
	for _, modelName := range fromSubmission {
		if strings.TrimSpace(modelName) == "" {
			continue
		}
		modelSet[modelName] = struct{}{}
	}

	var fromGenCode []string
	h.DB.Model(&model.GenCode{}).Distinct("model_name").Pluck("model_name", &fromGenCode)
	for _, modelName := range fromGenCode {
		if strings.TrimSpace(modelName) == "" {
			continue
		}
		modelSet[modelName] = struct{}{}
	}

	var fromTranslation []string
	h.DB.Model(&model.Translation{}).Distinct("model_name").Pluck("model_name", &fromTranslation)
	for _, modelName := range fromTranslation {
		if strings.TrimSpace(modelName) == "" {
			continue
		}
		modelSet[modelName] = struct{}{}
	}

	models := make([]string, 0, len(modelSet))
	for modelName := range modelSet {
		models = append(models, modelName)
	}
	slices.Sort(models)

	c.JSON(http.StatusOK, gin.H{"data": models})
}
