from pydantic import BaseModel, ConfigDict


class BaseModelWithOrm(BaseModel):
    model_config = ConfigDict(from_attributes=True)
